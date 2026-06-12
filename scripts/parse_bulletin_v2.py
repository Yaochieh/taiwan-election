"""
基於 PyMuPDF blocks 的公報解析器（v2）。

跟 v1 (parse_bulletin.py) 的差異：
  - v1 用 pdfplumber word-level 座標，適合 2022 臺北市公報的雙欄密集版面
  - v2 用 PyMuPDF blocks (PDF 結構化 textbox)，適合大版面、候選人數少的公報

策略：
  1. 用 DB 提供的候選人姓名作為錨點
  2. 在 PDF 中搜尋姓名位置（每位候選人的 column 位置）
  3. 找到每位候選人 column 的政見 block（通常是最大的文字塊）
  4. 擷取政見原文

用法：
  python scripts/parse_bulletin_v2.py <pdf_path> --names 林佳龍,侯友宜
  python scripts/parse_bulletin_v2.py <pdf_path> --election-id 49 --district "地區(65, 0, 0)"
"""
import argparse
import json
import sys
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def find_candidate_names_via_db(election_id: int, district: str | None = None) -> list[str]:
    """從 DB 取得某選舉的候選人姓名列表。"""
    from db.queries import get_connection
    with get_connection() as conn:
        if district:
            rows = conn.execute("""
                SELECT DISTINCT c.name
                FROM election_results er
                JOIN candidates c ON er.candidate_id = c.candidate_id
                WHERE er.election_id = ? AND er.district = ?
            """, (election_id, district)).fetchall()
        else:
            rows = conn.execute("""
                SELECT DISTINCT c.name
                FROM election_results er
                JOIN candidates c ON er.candidate_id = c.candidate_id
                WHERE er.election_id = ?
            """, (election_id,)).fetchall()
        return [r["name"] for r in rows]


def find_name_anchors(page, names: list[str]) -> dict[str, tuple]:
    """在 page 中找每位候選人姓名的位置。

    候選人姓名通常是 PDF 標題級的文字（大字、單獨一個 block）。
    若姓名沒整字、被拆成單字字符（直式版面），fallback 用 search_for 找連續字串。
    """
    blocks = page.get_text("blocks")
    anchors = {}

    for name in names:
        # 先找完整字串在某個 block 中
        for b in blocks:
            text = b[4]
            if name in text and len(text) < 30:
                # 短 block 含完整姓名 = 姓名位置
                x0, y0, x1, y1 = b[:4]
                anchors[name] = (x0, y0, x1, y1)
                break
        else:
            # search_for 找姓名（可能跨多個小 block）
            rects = page.search_for(name)
            if rects:
                r = rects[0]
                anchors[name] = (r.x0, r.y0, r.x1, r.y1)
    return anchors


def find_politics_block(page, name_anchor: tuple, all_anchors_y: list[float],
                       min_text_len: int = 80) -> str:
    """找姓名下方、長度最長的 block，視為政見。

    限制：
      - block 起始 y > 姓名 y + 50（在姓名下方）
      - block X 與姓名 X 重疊（同一欄）
      - block 文字長度 >= min_text_len（過濾學歷/經歷小 block）
      - block y 不超過下一個候選人錨點的 y
    """
    nx0, ny0, nx1, ny1 = name_anchor

    # 算出該 column 在 y 軸的下界（下一位候選人的 y，如果在同一頁）
    next_y = min(
        (y for y in all_anchors_y if y > ny0 + 200),
        default=page.rect.height,
    )

    blocks = page.get_text("blocks")
    candidates_blocks = []
    for b in blocks:
        x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
        text = text.strip()
        if not text or len(text) < min_text_len:
            continue
        # 要在姓名下方
        if y0 < ny0 + 30:
            continue
        # 同欄（X 軸重疊）— 寬鬆 80px
        if x1 < nx0 - 80 or x0 > nx1 + 80:
            continue
        # 不超過下個候選人
        if y0 > next_y:
            continue
        candidates_blocks.append((y0, len(text), text))

    if not candidates_blocks:
        return ""
    # 取第一個（最靠近姓名下方的）長 block 作為政見
    candidates_blocks.sort(key=lambda x: x[0])
    return candidates_blocks[0][2]


def parse_pdf(pdf_path: Path, names: list[str]) -> list[dict]:
    """掃描整個 PDF，對每位候選人找政見 block。"""
    doc = fitz.open(pdf_path)
    results = {n: "" for n in names}

    for page in doc:
        anchors = find_name_anchors(page, names)
        all_y = [v[1] for v in anchors.values()]
        for name, anchor in anchors.items():
            if results[name]:
                continue  # 已找到
            politics = find_politics_block(page, anchor, all_y)
            if politics:
                results[name] = politics

    return [{"name": n, "politics": results[n]} for n in names]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--names", help="候選人姓名（逗號分隔）")
    ap.add_argument("--election-id", type=int, help="從 DB 取得姓名")
    ap.add_argument("--district", help="篩選選區（搭配 --election-id）")
    args = ap.parse_args()

    if args.names:
        names = [n.strip() for n in args.names.split(",")]
    elif args.election_id:
        names = find_candidate_names_via_db(args.election_id, args.district)
    else:
        ap.error("須提供 --names 或 --election-id")

    print(f"目標候選人 ({len(names)} 位)：{names}", file=sys.stderr)
    results = parse_pdf(Path(args.pdf), names)
    for r in results:
        pol = r["politics"]
        print(f"\n=== {r['name']} ({len(pol)} 字) ===")
        print(pol[:500])
        if len(pol) > 500:
            print(f"... (+{len(pol)-500} 字)")


if __name__ == "__main__":
    main()
