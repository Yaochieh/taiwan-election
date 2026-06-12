"""
解析中選會選舉公報 PDF，抽取每位候選人的：
  - 號次、姓名、推薦政黨
  - 政見（原文）
  - 學歷、經歷
  - 出生年月、性別、出生地

版面（2022 直轄市長公報）：
  - A3 橫式，每頁 6 位候選人（左右 2 欄 × 3 列）
  - 每位候選人 block 用「政見」標籤定位
  - block 內版面：
      上半部：| 號次·姓名 | 學歷 | 經歷 |
      下半部：| 個人資料  | 政見              |

用法：
  python scripts/parse_bulletin.py <pdf_path>
  python scripts/parse_bulletin.py <pdf_path> --json
"""
import argparse
import json
import re
import sys
from pathlib import Path

import pdfplumber


def find_candidate_blocks(page) -> list[dict]:
    """每個「政見」標籤 = 一位候選人。回傳 block bbox。"""
    words = page.extract_words()
    pol_labels = [w for w in words if w["text"] == "政見"]
    blocks = []
    # 找到左欄/右欄的 X 中心點
    if not pol_labels:
        return []
    xs = sorted({round(w["x0"]) for w in pol_labels})

    # 估算左右欄分界
    page_mid = page.width / 2

    for w in pol_labels:
        cx = w["x0"]
        cy = w["top"]
        is_left = cx < page_mid
        if is_left:
            x0, x1 = 0, page_mid
        else:
            x0, x1 = page_mid, page.width
        y0 = max(0, cy - 280)
        y1 = min(page.height, cy + 300)
        blocks.append({
            "bbox": (x0, y0, x1, y1),
            "pol_x": cx,
            "pol_y": cy,
            "is_left": is_left,
        })
    return blocks


def words_in(page, bbox):
    x0, y0, x1, y1 = bbox
    return [
        w for w in page.extract_words()
        if w["x0"] >= x0 and w["x0"] < x1 and w["top"] >= y0 and w["top"] < y1
    ]


def join_lines(words: list[dict], y_tol: int = 5) -> str:
    """依 y 分行、x 排序、串接。"""
    if not words:
        return ""
    sorted_w = sorted(words, key=lambda w: (round(w["top"] / y_tol) * y_tol, w["x0"]))
    lines = []
    cur = []
    cur_y = None
    for w in sorted_w:
        if cur_y is None or abs(w["top"] - cur_y) <= y_tol:
            cur.append(w)
            cur_y = w["top"] if cur_y is None else cur_y
        else:
            lines.append("".join(s["text"] for s in cur))
            cur = [w]
            cur_y = w["top"]
    if cur:
        lines.append("".join(s["text"] for s in cur))
    return "\n".join(l for l in lines if l.strip())


def parse_block(page, blk) -> dict:
    x0, y0, x1, y1 = blk["bbox"]
    pol_x, pol_y = blk["pol_x"], blk["pol_y"]

    all_words = words_in(page, blk["bbox"])

    # ── 找個人資料標籤位置（block 內 x < pol_x）──
    personal_label = None
    for w in all_words:
        if w["text"] == "個人資料" and w["x0"] < pol_x:
            personal_label = w
            break
    personal_x_end = (personal_label["x0"] + 120) if personal_label else (x0 + (x1 - x0) * 0.25)

    # ── 切上下半 ──
    upper_words = [w for w in all_words if w["top"] < pol_y - 5]
    lower_words = [w for w in all_words if w["top"] >= pol_y - 5]

    # ── 政見：lower_words 中 x > personal_x_end ──
    politics_words = [
        w for w in lower_words
        if w["x0"] > personal_x_end
        and w["text"] not in ("政見",)
    ]
    politics = join_lines(politics_words)
    # 後處理：截除下一位候選人的學歷/經歷開頭
    politics = re.split(r"\n?學歷\s*經歷\n?", politics)[0].strip()
    politics = re.split(r"\n號次", politics)[0].strip()

    # ── 個人資料：lower_words 中 x <= personal_x_end ──
    personal_words = [
        w for w in lower_words
        if w["x0"] <= personal_x_end
        and w["text"] not in ("個人資料",)
    ]
    personal_text = join_lines(personal_words)

    # ── 上半部找學歷/經歷標題位置 ──
    edu_label = next((w for w in upper_words if w["text"] == "學歷"), None)
    exp_label = next((w for w in upper_words if w["text"] == "經歷"), None)
    name_label = next((w for w in upper_words if w["text"] == "號次·姓名"), None)

    cand_num = None
    name = ""
    education = ""
    experience = ""

    if name_label and edu_label and exp_label:
        name_x_end = edu_label["x0"] - 10
        edu_x_end = exp_label["x0"] - 10

        # 姓名/號次區塊：name_label.x 附近 30px 內（姓名靠左對齊）
        name_zone = [
            w for w in upper_words
            if abs(w["x0"] - name_label["x0"]) < 35
            and w["top"] > name_label["top"] + 10
        ]
        # 號次（純數字）
        nums = [w for w in name_zone if re.fullmatch(r"\d{1,2}", w["text"])]
        if nums:
            nums.sort(key=lambda w: w["top"])
            cand_num = int(nums[0]["text"])
        # 姓名：2-4 字中文，靠最下面（最大 top）
        cn_names = [
            w for w in name_zone
            if re.fullmatch(r"[一-鿿]{2,5}", w["text"])
        ]
        if cn_names:
            cn_names.sort(key=lambda w: -w["top"])
            name = cn_names[0]["text"]

        # 學歷
        edu_zone = [
            w for w in upper_words
            if edu_label["x0"] - 30 <= w["x0"] < edu_x_end
            and w["top"] > edu_label["top"] + 10
        ]
        education = join_lines(edu_zone)

        # 經歷
        exp_zone = [
            w for w in upper_words
            if w["x0"] >= exp_label["x0"] - 30
            and w["top"] > exp_label["top"] + 10
        ]
        experience = join_lines(exp_zone)

    # ── 從個人資料文字解出政黨/出生年/性別/出生地 ──
    party = ""
    birth = ""
    gender = ""
    birthplace = ""

    # 推薦之政黨：找標籤的 word，取其下方第一行文字
    party_label = next(
        (w for w in personal_words if w["text"] in ("推薦之政黨", "推薦政黨")),
        None,
    )
    # 標籤有時被切成多段，補一個 fallback
    if not party_label:
        for w in personal_words:
            if w["text"].startswith("推薦"):
                party_label = w
                break
    if party_label:
        below = [
            w for w in personal_words
            if w["top"] > party_label["top"] + 8
            and abs(w["x0"] - party_label["x0"]) < 100
        ]
        if below:
            below.sort(key=lambda w: (w["top"], w["x0"]))
            first_y = below[0]["top"]
            party = "".join(
                w["text"] for w in below if abs(w["top"] - first_y) < 8
            ).strip()

    m = re.search(r"(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})", personal_text)
    if m:
        birth = f"{m.group(1)}/{int(m.group(2)):02d}/{int(m.group(3)):02d}"
    else:
        # 從 word 級找：在「出生年月日：」標籤右側、上方一行的三個數字
        date_label = next(
            (w for w in personal_words if "出生年月日" in w["text"]), None
        )
        if date_label:
            nearby_nums = [
                w for w in personal_words
                if re.fullmatch(r"\d{1,3}", w["text"])
                and w["x0"] > date_label["x0"] + 30
                and abs(w["top"] - date_label["top"]) < 15
            ]
            nearby_nums.sort(key=lambda w: w["x0"])
            if len(nearby_nums) >= 3:
                y, m_, d = nearby_nums[:3]
                birth = f"{y['text']}/{int(m_['text']):02d}/{int(d['text']):02d}"

    m = re.search(r"性別\s*[：:]*\s*([男女])", personal_text)
    if m:
        gender = m.group(1)

    m = re.search(r"出生地\s*[：:]*\s*(.+)", personal_text)
    if m:
        birthplace = m.group(1).split("\n")[0].strip()

    return {
        "cand_num": cand_num,
        "name": name,
        "party": party,
        "birth_minguo": birth,
        "gender": gender,
        "birthplace": birthplace,
        "education": education,
        "experience": experience,
        "politics": politics,
        "_personal_raw": personal_text,
    }


def parse_pdf(pdf_path: Path) -> list[dict]:
    candidates = []
    with pdfplumber.open(pdf_path) as pdf:
        for p_idx, page in enumerate(pdf.pages):
            for blk in find_candidate_blocks(page):
                c = parse_block(page, blk)
                c["page"] = p_idx + 1
                candidates.append(c)

    # 排序並去重複（同號次）
    by_num = {}
    for c in candidates:
        if c["cand_num"] and c["cand_num"] not in by_num:
            by_num[c["cand_num"]] = c
        elif not c["cand_num"]:
            by_num[f"_no_num_{len(by_num)}"] = c
    return [by_num[k] for k in sorted(by_num.keys(),
                                       key=lambda x: x if isinstance(x, int) else 999)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"找不到 {pdf_path}", file=sys.stderr)
        sys.exit(1)

    candidates = parse_pdf(pdf_path)

    if args.json:
        clean = [{k: v for k, v in c.items() if not k.startswith("_")} for c in candidates]
        print(json.dumps(clean, ensure_ascii=False, indent=2))
        return

    for c in candidates:
        print(f"\n{'='*70}")
        print(f"  號次 {c['cand_num']}  姓名 [{c['name']}]  推薦政黨 [{c['party']}]")
        print(f"  生日 {c['birth_minguo']}  性別 {c['gender']}  出生地 {c['birthplace']}")
        print(f"  --- 學歷 ---")
        print(f"  {c['education'][:300]}")
        print(f"  --- 經歷 ---")
        print(f"  {c['experience'][:300]}")
        print(f"  --- 政見 ---")
        print(f"  {c['politics'][:500]}")


if __name__ == "__main__":
    main()
