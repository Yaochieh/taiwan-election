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

    優先找短 block (≤30 字) 含姓名（標題級）；找不到才用 search_for 搜尋字串。
    """
    blocks = page.get_text("blocks")
    anchors = {}

    for name in names:
        # Strategy 1: 找短 block 含姓名
        found = None
        for b in blocks:
            text = b[4]
            if name in text and len(text.strip()) < 30:
                found = b[:4]
                break

        # Strategy 2: fallback 用 search_for（適合單字垂直排列的版面）
        if not found:
            rects = page.search_for(name)
            if rects:
                r = rects[0]
                found = (r.x0, r.y0, r.x1, r.y1)

        if found:
            anchors[name] = found
    return anchors


def find_politics_block(page, name_anchor: tuple, all_anchors_y: list[float],
                       min_text_len: int = 80, max_distance: float = 600) -> str:
    """找姓名下方、長度最長的 block，視為政見。

    限制：
      - block 起始 y > 姓名 y + 50（在姓名下方）
      - block 起始 y - 姓名 y <= max_distance（不抓到頁面下半的其他候選人區）
      - block X 與姓名 X 重疊（同一欄）
      - block 文字長度 >= min_text_len（過濾學歷/經歷小 block）
      - block y 不超過下一個候選人錨點的 y
    """
    nx0, ny0, nx1, ny1 = name_anchor

    # 算出該 column 在 y 軸的下界（下一位候選人的 y，如果在同一頁）
    next_y = min(
        (y for y in all_anchors_y if y > ny0 + 200),
        default=ny0 + max_distance,
    )
    upper_bound = min(next_y, ny0 + max_distance)

    blocks = page.get_text("blocks")
    candidates_blocks = []
    for b in blocks:
        x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
        text = text.strip()
        if not text or len(text) < min_text_len:
            continue
        # 同欄（X 軸重疊）— 寬鬆 80px
        if x1 < nx0 - 80 or x0 > nx1 + 80:
            continue
        # 政見 block 結尾必須在姓名下方一段距離（允許 block 起始略早，但結尾必須足夠下方）
        if y1 < ny0 + 100:
            continue
        # block 起始 y 不超過下個候選人或最大距離
        if y0 > upper_bound:
            continue
        # 排除「跨候選人」的大 block：高度不能太大
        if y1 - y0 > 800:
            continue
        # 政見 block 距姓名 y 不能太遠（避免抓到頁面其他區域候選人的 block）
        if y0 > ny0 + 450:
            continue
        candidates_blocks.append((y0, len(text), text))

    if not candidates_blocks:
        return ""
    # 取最靠近姓名（y 最接近）的長 block 作為政見
    candidates_blocks.sort(key=lambda x: abs(x[0] - ny0))
    return candidates_blocks[0][2]


def parse_pdf(pdf_path: Path, names: list[str], max_pages: int = 1) -> list[dict]:
    """掃描 PDF 前 max_pages 頁，對每位候選人找政見 block。

    直轄市長公報的候選人資訊通常都在第 1 頁；後面頁面是議員。
    限制 max_pages=1 可避免誤抓到議員候選人的政見。
    """
    doc = fitz.open(pdf_path)
    results = {n: "" for n in names}

    pages_to_scan = min(doc.page_count, max_pages)
    for p_idx in range(pages_to_scan):
        page = doc[p_idx]
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
