"""
對 2014/2018 縣市長公報 PDF 整頁渲染成圖片後跑 OCR，
再用候選人姓名 anchor 切出每位的政見區段，存入 platforms / platform_sources。

跟 extract_bulletin_images.py 不同：那個只抓 PDF 內嵌寬幅圖片（很多公報沒有），
這個是整頁 raster + OCR，理論上能 cover 所有版面。

執行：
  python scripts/ocr_bulletin_pages.py --pdf <pdf> --election-id 33 --district "地區(63, 0, 0)"
  python scripts/ocr_bulletin_pages.py --all  # 跑全部 2014/2018 縣市長
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "db.sqlite"
OUT_DIR = ROOT / "data" / "bulletin_pages"

JOBS = [
    (33, "data/bulletins/01選舉公報/03直轄市長/103年", "地區(63, 0, 0)", "01臺北市市長.pdf"),
    (33, "data/bulletins/01選舉公報/03直轄市長/103年", "地區(65, 0, 0)", "02新北市市長.pdf"),
    (33, "data/bulletins/01選舉公報/03直轄市長/103年", "地區(68, 0, 0)", "03桃園市市長.pdf"),
    (33, "data/bulletins/01選舉公報/03直轄市長/103年", "地區(66, 0, 0)", "04臺中市市長.pdf"),
    (33, "data/bulletins/01選舉公報/03直轄市長/103年", "地區(67, 0, 0)", "05臺南市市長.pdf"),
    (33, "data/bulletins/01選舉公報/03直轄市長/103年", "地區(64, 0, 0)", "06高雄市市長.pdf"),
    (42, "data/bulletins/01選舉公報/03直轄市長/107年", "地區(63, 0, 0)", "臺北市市長.pdf"),
    (42, "data/bulletins/01選舉公報/03直轄市長/107年", "地區(65, 0, 0)", "新北市市長.pdf"),
    (42, "data/bulletins/01選舉公報/03直轄市長/107年", "地區(68, 0, 0)", "桃園市市長.pdf"),
    (42, "data/bulletins/01選舉公報/03直轄市長/107年", "地區(66, 0, 0)", "臺中市市長.pdf"),
    (42, "data/bulletins/01選舉公報/03直轄市長/107年", "地區(67, 0, 0)", "臺南市市長.pdf"),
    (42, "data/bulletins/01選舉公報/03直轄市長/107年", "地區(64, 0, 0)", "高雄市市長.pdf"),
]


def render_page(pdf_path: Path, page_idx: int, dpi: int = 200) -> Path:
    out = OUT_DIR / f"{pdf_path.stem}_p{page_idx + 1}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return out
    doc = fitz.open(pdf_path)
    page = doc[page_idx]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    pix.save(str(out))
    doc.close()
    return out


def ocr_image(ocr, image_path: Path):
    """回傳 [(text, [(x0,y0,x1,y1)]), ...]，按閱讀順序排列。"""
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


def find_name_y(items: list, name: str) -> float | None:
    """在 OCR 結果中找姓名所在的 y。整名連續或拆字皆可。"""
    # 整名出現
    for t, bbox in items:
        if name == t.strip():
            return (bbox[1] + bbox[3]) / 2
    # 部分相符
    for t, bbox in items:
        if t.strip() == name:
            return (bbox[1] + bbox[3]) / 2
    # 拆字：搜尋 name 第一個字大且後續字接近的列
    return None


def extract_politics_text(items: list, names: list[str]) -> dict[str, str]:
    """為每位候選人切出政見：
    策略：找每個 name 的 y 位置，下一個 name 的 y 是該位候選人的下界；
    取該範圍內所有文字按 y 排序拼起來，去除短雜訊。
    """
    name_y = {}
    for n in names:
        y = find_name_y(items, n)
        if y is not None:
            name_y[n] = y
    if not name_y:
        return {n: "" for n in names}

    sorted_names = sorted(name_y.items(), key=lambda x: x[1])
    result = {}
    page_max_y = max(b[3] for _, b in items) if items else 1e9
    for i, (n, y_start) in enumerate(sorted_names):
        y_end = sorted_names[i + 1][1] - 10 if i + 1 < len(sorted_names) else page_max_y
        # 收集此範圍內文字（排除姓名本身及短雜訊）
        in_range = [
            (b[1], t)
            for t, b in items
            if y_start - 5 < (b[1] + b[3]) / 2 < y_end and len(t) >= 4
        ]
        in_range.sort()
        result[n] = "\n".join(t for _, t in in_range)
    for n in names:
        result.setdefault(n, "")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf")
    ap.add_argument("--election-id", type=int)
    ap.add_argument("--district")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-pages", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.all:
        jobs = [(eid, d, dist, fn) for eid, d, dist, fn in JOBS]
    else:
        if not args.pdf or not args.election_id or not args.district:
            ap.error("--pdf, --election-id, --district 必須提供（或用 --all）")
        jobs = [(args.election_id, str(Path(args.pdf).parent), args.district, Path(args.pdf).name)]

    print("初始化 PaddleOCR…")
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    grand_imported = 0
    for eid, base, district, fn in jobs:
        pdf = ROOT / base / fn
        if not pdf.exists():
            print(f"✗ {pdf} 不存在")
            continue
        print(f"\n=== eid={eid} {district} {fn} ===")

        # 撈該 district 候選人
        rows = conn.execute(
            "SELECT DISTINCT c.candidate_id, c.name "
            "FROM election_results er JOIN candidates c ON er.candidate_id=c.candidate_id "
            "WHERE er.election_id=? AND er.district=?",
            (eid, district),
        ).fetchall()
        names = [r["name"] for r in rows]
        name_to_id = {r["name"]: r["candidate_id"] for r in rows}
        if not names:
            print("  ✗ 找不到候選人")
            continue
        print(f"  目標 {len(names)} 位")

        # OCR 第 1 頁（縣市長公報候選人通常都在 p1）
        page_path = render_page(pdf, 0)
        print(f"  渲染 → {page_path.name}")
        items = ocr_image(ocr, page_path)
        print(f"  OCR 得 {len(items)} 段文字")

        politics_by_name = extract_politics_text(items, names)
        imported = 0
        for n, text in politics_by_name.items():
            cid = name_to_id[n]
            text = text.strip()
            if not text or len(text) < 30:
                print(f"  - {n}: 政見過短 ({len(text)} 字)，略")
                continue
            # 是否已存在
            ex = conn.execute(
                "SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=? AND seq=1",
                (cid, eid),
            ).fetchone()
            if ex:
                print(f"  - {n}: 已有政見，跳過 (OCR {len(text)} 字)")
                continue
            print(f"  + {n}: {len(text)} 字")
            if args.dry_run:
                continue
            conn.execute(
                "INSERT INTO platforms (candidate_id, election_id, seq, title, content) "
                "VALUES (?, ?, 1, NULL, ?)",
                (cid, eid, text),
            )
            conn.execute(
                "INSERT INTO platform_sources "
                "(candidate_id, election_id, source_type, local_path, description) "
                "VALUES (?, ?, 'page_ocr', ?, ?)",
                (cid, eid, str(page_path.relative_to(ROOT)), "整頁 OCR"),
            )
            imported += 1
        if not args.dry_run:
            conn.commit()
        print(f"  ✓ 新增 {imported} 條政見")
        grand_imported += imported

    print(f"\n總計新增 {grand_imported} 條政見")
    conn.close()


if __name__ == "__main__":
    main()
