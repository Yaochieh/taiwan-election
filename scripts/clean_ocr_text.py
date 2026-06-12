"""
後處理 OCR 文字：修復斷句、合併編號、清理雜訊。

問題類別：
1. 行尾被切斷（沒句號結束就換行）→ 合併下行
2. 短編號獨立成行（「1.」「2.」「(1)」「一、」「0-6」）→ 與下行合併
3. 連續多個空白行 → 合併成單一段落分隔

執行：
  python scripts/clean_ocr_text.py                       # 處理全部
  python scripts/clean_ocr_text.py --candidate 蔣萬安    # 試單人
  python scripts/clean_ocr_text.py --dry-run             # 不寫入 DB
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"

# 句尾標點（保留換行）
SENTENCE_END = "。！？!?；;"
# 標點（允許作為換行依據）
PUNCT_END = SENTENCE_END + "：、，,."

# 短編號 / 條目開頭模式
NUMBER_PREFIX_PATTERNS = [
    r"^[（(]\d{1,2}[)）][\s.]*$",   # (1) (2)
    r"^\d{1,2}[.、][\s]*$",         # 1. 2.
    r"^[一二三四五六七八九十百]{1,3}[、.]\s*$",  # 一、 二、
    r"^[•·●○◎\-－]+\s*$",          # bullets
    r"^\d{1,2}[-－—]\d{1,2}\s*$",   # 0-6 (range)
    r"^[\s\d]+$",                   # 純數字短行
]


def is_short_prefix(line: str) -> bool:
    """是否為短的編號 / 條目開頭。"""
    line = line.strip()
    if not line or len(line) > 10:
        return False
    for pat in NUMBER_PREFIX_PATTERNS:
        if re.match(pat, line):
            return True
    return False


def is_number_only(line: str) -> bool:
    """純數字 / 範圍（如「0-6」「2025」）。"""
    return bool(re.match(r"^[\d\s\-－—]+$", line.strip()))


def clean_ocr(text: str) -> str:
    if not text:
        return text

    # 1. 先正規化：把所有空白行刪除，把多重換行統一
    lines = [l.strip() for l in text.split("\n")]
    # 移除空行
    lines = [l for l in lines if l]

    if not lines:
        return ""

    # 2. 合併斷句
    merged: list[str] = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        # 若此行是短編號開頭、且不是最後一行，合併下一行
        while is_short_prefix(cur) and i + 1 < len(lines):
            cur = cur + " " + lines[i + 1]
            i += 1

        # 若此行純數字短行（如「0-6」），且下一行是中文，合併
        if is_number_only(cur) and len(cur.strip()) <= 6 and i + 1 < len(lines):
            next_line = lines[i + 1]
            if next_line and re.match(r"[一-鿿「『]", next_line):
                cur = cur + " " + next_line
                i += 1

        # 若此行尾不是句號 / 標點，且下一行不是新編號開頭，合併
        while (
            i + 1 < len(lines)
            and cur
            and cur[-1] not in SENTENCE_END
            and not is_short_prefix(lines[i + 1])
            and not re.match(r"^[（(]\d", lines[i + 1])
            and not re.match(r"^\d{1,2}[.、]", lines[i + 1])
            and not re.match(r"^[一二三四五六七八九十]{1,3}[、.]", lines[i + 1])
        ):
            # 中文之間不加空格，中英文之間加空格
            next_line = lines[i + 1]
            if cur[-1].isascii() or next_line[0].isascii():
                cur = cur + " " + next_line
            else:
                cur = cur + next_line
            i += 1

        merged.append(cur)
        i += 1

    # 3. 修整每行內部
    cleaned = []
    for line in merged:
        # 連續空白合一
        line = re.sub(r"\s{2,}", " ", line)
        # 全形句號後面接空白
        line = re.sub(r"([。！？])(?=\S)", r"\1 ", line)
        cleaned.append(line.strip())

    # 4. 移除結尾的「明確雜訊」數字殘留：純單數字（≤2 字）+ 編號（含 .、）
    # 不移除有意義的數字範圍（如「0-6」）或多位數（如「2025」「1000」）
    while cleaned:
        last = cleaned[-1].strip()
        # 只清純 1-2 位數字或純編號樣式（"1." "2、"）
        if (re.match(r"^\d{1,2}$", last)
                or re.match(r"^\d{1,2}[.、]$", last)
                or re.match(r"^[\s.、]+$", last)):
            cleaned.pop()
        else:
            break

    # 5. 同理移除開頭的雜訊
    while cleaned:
        first = cleaned[0].strip()
        if (re.match(r"^\d{1,2}$", first)
                or re.match(r"^\d{1,2}[.、]$", first)
                or re.match(r"^[\s.、]+$", first)):
            cleaned.pop(0)
        else:
            break

    return "\n".join(cleaned)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", help="只處理特定候選人姓名")
    ap.add_argument("--dry-run", action="store_true", help="不寫入 DB，只印結果")
    ap.add_argument("--also-text-platforms", action="store_true",
                    help="同時清理 platforms 表（PDF 文字版）")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    where = ["source_type = 'image_platform'", "ocr_text IS NOT NULL", "ocr_text != ''"]
    params: list = []
    if args.candidate:
        where.append("candidate_id IN (SELECT candidate_id FROM candidates WHERE name = ?)")
        params.append(args.candidate)

    rows = conn.execute(
        f"SELECT source_id, candidate_id, ocr_text FROM platform_sources "
        f"WHERE {' AND '.join(where)} ORDER BY source_id",
        params,
    ).fetchall()

    print(f"📋 處理 {len(rows)} 筆 OCR 文字")

    for r in rows:
        cand = conn.execute(
            "SELECT name FROM candidates WHERE candidate_id = ?",
            (r["candidate_id"],),
        ).fetchone()
        name = cand["name"] if cand else f"id={r['candidate_id']}"

        original = r["ocr_text"]
        cleaned = clean_ocr(original)

        if args.dry_run:
            print(f"\n=== {name} ({len(original)} → {len(cleaned)} 字) ===")
            print(cleaned[:500])
            if len(cleaned) > 500:
                print(f"...（共 {len(cleaned)} 字）")
        else:
            # 把清理後的版本存到 ocr_text；原版可另存到 ocr_text_raw（未實作）
            conn.execute(
                "UPDATE platform_sources SET ocr_text = ? WHERE source_id = ?",
                (cleaned, r["source_id"]),
            )
            print(f"  ✓ {name}：{len(original)} → {len(cleaned)} 字")

    if not args.dry_run:
        conn.commit()
        print(f"\n✓ 清理完成，已更新 DB（OCR 圖檔文字）")

    # ── 同時清理 platforms 表（PDF 文字版政見）──
    if args.also_text_platforms:
        text_where = ["content IS NOT NULL", "content != ''"]
        text_params = []
        if args.candidate:
            text_where.append("candidate_id IN (SELECT candidate_id FROM candidates WHERE name = ?)")
            text_params.append(args.candidate)
        text_rows = conn.execute(
            f"SELECT platform_id, candidate_id, content FROM platforms "
            f"WHERE {' AND '.join(text_where)}",
            text_params,
        ).fetchall()
        print(f"\n📋 PDF 文字版政見：{len(text_rows)} 筆")

        for r in text_rows:
            cand = conn.execute(
                "SELECT name FROM candidates WHERE candidate_id = ?",
                (r["candidate_id"],),
            ).fetchone()
            name = cand["name"] if cand else f"id={r['candidate_id']}"

            original = r["content"]
            cleaned = clean_ocr(original)
            if args.dry_run:
                if original != cleaned:
                    print(f"  {name} (#{r['platform_id']}): {len(original)} → {len(cleaned)}")
                    print(f"    BEFORE: {original[:80].replace(chr(10), ' / ')}")
                    print(f"    AFTER:  {cleaned[:80].replace(chr(10), ' / ')}")
            else:
                conn.execute(
                    "UPDATE platforms SET content = ? WHERE platform_id = ?",
                    (cleaned, r["platform_id"]),
                )

        if not args.dry_run:
            conn.commit()
            print(f"✓ 清理完成（PDF 文字版）")

    conn.close()


if __name__ == "__main__":
    main()
