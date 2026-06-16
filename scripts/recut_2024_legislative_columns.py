"""
重新切 2024 區域立委 OCR 結果 — column-aware 版本。

之前用「按 y 切」會讓多欄 PDF 內容混在一起。
這版根據姓名的 x 位置定義欄位邊界，每位候選人只取自己欄位內的文字。

執行：
  python scripts/recut_2024_legislative_columns.py
"""
import sqlite3
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "db.sqlite"
OUT_DIR = ROOT / "data" / "bulletin_pages_legislators"
PDF_ROOT = ROOT / "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員"

ELECTION_ID = 51


def parse_district_from_path(pdf_path: Path) -> str | None:
    import re

    parts = pdf_path.parts
    county = None
    for part in parts:
        m = re.match(r"^\d{2}(.+)$", part)
        if m and ("縣" in m.group(1) or "市" in m.group(1)):
            county = m.group(1).replace("台", "臺")
            break
    if not county:
        return None
    parent = pdf_path.parent.name
    m = re.search(r"第(\d+)選舉區", parent + " " + pdf_path.name)
    if m:
        return f"{county}第{int(m.group(1)):02d}選區"
    return None


def render_pages(pdf_path: Path, max_pages: int = 4, dpi: int = 200) -> list[Path]:
    doc = fitz.open(pdf_path)
    paths = []
    safe_stem = pdf_path.stem.replace("/", "_")
    for i in range(min(max_pages, doc.page_count)):
        out = OUT_DIR / f"{safe_stem}_{pdf_path.parent.name}_p{i+1}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = doc[i].get_pixmap(matrix=mat)
            pix.save(str(out))
        paths.append(out)
    doc.close()
    return paths


def ocr_image(ocr, image_path: Path):
    result = ocr.predict(str(image_path))
    out = []
    for page in result:
        if isinstance(page, dict):
            texts = page.get("rec_texts", [])
            polys = page.get("rec_polys", [])
            scores = page.get("rec_scores", [])
            for t, poly, s in zip(texts, polys, scores):
                if s and s > 0.5:
                    xs = [p[0] for p in poly]
                    ys = [p[1] for p in poly]
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    out.append((t.strip(), bbox))
    return out


def extract_per_column(items_per_page: list[list], names: list[str]) -> dict[str, str]:
    """跨頁 OCR 結果 → 按 column 提取各候選人內容。
    items_per_page: 每頁的 [(text, bbox)]
    """
    result = {n: [] for n in names}

    for page_idx, page_items in enumerate(items_per_page):
        if not page_items:
            continue
        # 找出每位候選人在這頁的 (x_center, y)
        name_positions: list[tuple[str, float, float]] = []
        for n in names:
            for t, bbox in page_items:
                if t.strip() == n:
                    x_c = (bbox[0] + bbox[2]) / 2
                    y_top = bbox[1]
                    name_positions.append((n, x_c, y_top))
                    break
            else:
                # prefix match
                if len(n) >= 2:
                    prefix = n[:2]
                    for t, bbox in page_items:
                        tt = t.strip()
                        if tt.startswith(prefix) and len(tt) <= len(n) + 8:
                            x_c = (bbox[0] + bbox[2]) / 2
                            y_top = bbox[1]
                            name_positions.append((n, x_c, y_top))
                            break

        if not name_positions:
            continue

        # 按 x 排序
        name_positions.sort(key=lambda x: x[1])

        # 定義每位的 x 範圍：從前一位中點到下一位中點
        page_max_x = max(b[2] for _, b in page_items)
        page_max_y = max(b[3] for _, b in page_items)
        for i, (n, x_c, y_top) in enumerate(name_positions):
            x_left = (name_positions[i - 1][1] + x_c) / 2 if i > 0 else 0
            x_right = (
                (name_positions[i + 1][1] + x_c) / 2
                if i + 1 < len(name_positions)
                else page_max_x
            )
            # 該位候選人的 y 範圍：name_y 下面
            y_min = y_top
            y_max = page_max_y

            # 收集這個矩形內的文字（排除姓名本身、排除短雜訊）
            in_col = []
            for t, bbox in page_items:
                tx_c = (bbox[0] + bbox[2]) / 2
                ty_c = (bbox[1] + bbox[3]) / 2
                if x_left < tx_c < x_right and y_min <= ty_c <= y_max:
                    tt = t.strip()
                    if len(tt) >= 4 and tt != n:
                        in_col.append((bbox[1], tt))
            in_col.sort()
            result[n].extend(t for _, t in in_col)

    return {n: "\n".join(result[n]) for n in names}


def main():
    print("初始化 PaddleOCR…")
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    pdf_files = sorted(PDF_ROOT.rglob("*.pdf"))
    print(f"📋 {len(pdf_files)} 個 PDF")

    grand_replaced = 0
    for pdf in pdf_files:
        district = parse_district_from_path(pdf)
        if not district:
            continue
        rows = conn.execute(
            "SELECT DISTINCT c.candidate_id, c.name "
            "FROM election_results er JOIN candidates c ON er.candidate_id=c.candidate_id "
            "WHERE er.election_id=? AND er.district=?",
            (ELECTION_ID, district),
        ).fetchall()
        if not rows:
            continue
        names = [r["name"] for r in rows]
        name_to_id = {r["name"]: r["candidate_id"] for r in rows}
        # 只重做有 platform 的候選人（OCR 已跑過，重新切）
        has_pf = [
            n for n in names
            if conn.execute(
                "SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=?",
                (name_to_id[n], ELECTION_ID),
            ).fetchone()
        ]
        if not has_pf:
            continue

        page_paths = render_pages(pdf)
        items_per_page = []
        for p in page_paths:
            items_per_page.append(ocr_image(ocr, p))

        politics = extract_per_column(items_per_page, names)

        replaced = 0
        for n in has_pf:
            text = politics.get(n, "").strip()
            if not text or len(text) < 30:
                continue
            cid = name_to_id[n]
            conn.execute(
                "UPDATE platforms SET content=? WHERE candidate_id=? AND election_id=? AND seq=1",
                (text, cid, ELECTION_ID),
            )
            replaced += 1
        conn.commit()
        if replaced:
            print(f"  {district}: 重切 {replaced} 條")
            grand_replaced += replaced

    print(f"\n總計重切 {grand_replaced} 條政見")
    conn.close()


if __name__ == "__main__":
    main()
