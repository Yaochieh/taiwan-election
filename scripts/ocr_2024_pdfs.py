"""
2024 (113 年) 總統 + 立委各種公報的 OCR：

包含：
  - 2024 總統 (2 頁)
  - 2024 山地原住民立委 (n 頁)
  - 2024 平地原住民立委 (n 頁)
  - 2024 不分區政黨 (4 頁) — 政黨層級的政見 + 候選人政見

跟 ocr_bulletin_pages.py 不同：這個專處理多頁 PDF 且不限於縣市長。

執行：
  python scripts/ocr_2024_pdfs.py
"""
import re
import sqlite3
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "db.sqlite"
OUT_DIR = ROOT / "data" / "bulletin_pages"

JOBS = [
    # (election_id, pdf_path, max_pages, label)
    (54, "data/bulletins/01選舉公報/01總統副總統/113年第16任總統副總統.pdf", 2, "2024總統"),
    (52, "data/bulletins/01選舉公報/02立法委員/113年第11屆/04山地原住民立法委員/山地原住民立法委員.pdf", 4, "2024山原立委"),
    (53, "data/bulletins/01選舉公報/02立法委員/113年第11屆/03平地原住民立法委員/平地原住民立法委員.pdf", 4, "2024平原立委"),
    (50, "data/bulletins/01選舉公報/02立法委員/113年第11屆/05全國不分區及僑居國外國民立法委員/全國不分區及僑居國外國民立法委員.pdf", 4, "2024不分區"),
]


def render_pages(pdf_path: Path, max_pages: int, dpi: int = 200) -> list[Path]:
    doc = fitz.open(pdf_path)
    paths = []
    for i in range(min(max_pages, doc.page_count)):
        out = OUT_DIR / f"{pdf_path.stem}_p{i+1}.png"
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


def find_name_y_first_match(items: list, name: str):
    """支援部分匹配（用於含拼音的原住民名字）。回傳 (page_idx, y)。"""
    # 試完整 match
    for idx, (t, bbox) in enumerate(items):
        if t.strip() == name:
            return idx, (bbox[1] + bbox[3]) / 2
    # 試 prefix 2 字
    if len(name) >= 2:
        prefix = name[:2]
        for idx, (t, bbox) in enumerate(items):
            tt = t.strip()
            if tt.startswith(prefix) and len(tt) <= len(name) + 4:
                return idx, (bbox[1] + bbox[3]) / 2
    return None, None


def extract_per_candidate(all_items: list, names: list[str]) -> dict[str, str]:
    """從跨頁的 OCR items（每個 item 含 (text, bbox, page_idx)）切出每位候選人政見。"""
    # all_items: list of (text, (x0,y0,x1,y1), page_idx, abs_y)
    # 用 abs_y = page_idx * 10000 + y 確保跨頁順序
    name_pos = {}
    for n in names:
        for t, bbox, page_idx, abs_y in all_items:
            if t.strip() == n:
                name_pos[n] = abs_y
                break
        if n in name_pos:
            continue
        # prefix match
        if len(n) >= 2:
            prefix = n[:2]
            for t, bbox, page_idx, abs_y in all_items:
                tt = t.strip()
                if tt.startswith(prefix) and len(tt) <= len(n) + 6:
                    name_pos[n] = abs_y
                    break
    if not name_pos:
        return {n: "" for n in names}
    sorted_names = sorted(name_pos.items(), key=lambda x: x[1])
    max_y = max(item[3] for item in all_items) if all_items else 1e9
    result = {}
    for i, (n, y_start) in enumerate(sorted_names):
        y_end = sorted_names[i + 1][1] - 5 if i + 1 < len(sorted_names) else max_y
        # 收集此範圍內文字（排除短雜訊）
        in_range = [
            (abs_y, t)
            for t, _, _, abs_y in all_items
            if y_start - 5 < abs_y < y_end and len(t) >= 4
        ]
        in_range.sort()
        result[n] = "\n".join(t for _, t in in_range)
    for n in names:
        result.setdefault(n, "")
    return result


def main():
    print("初始化 PaddleOCR…")
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    grand = 0
    for election_id, pdf_rel, max_pages, label in JOBS:
        pdf = ROOT / pdf_rel
        if not pdf.exists():
            print(f"✗ {pdf} 不存在")
            continue
        print(f"\n=== {label} (election_id={election_id}) ===")

        rows = conn.execute(
            "SELECT candidate_id, name FROM candidates WHERE election_id=?",
            (election_id,),
        ).fetchall()
        names = [r["name"] for r in rows]
        name_to_id = {r["name"]: r["candidate_id"] for r in rows}
        if not names:
            print(f"  ✗ 無候選人")
            continue
        print(f"  {len(names)} 候選人")

        # 渲染 + OCR 所有頁
        all_items = []
        page_paths = render_pages(pdf, max_pages)
        for page_idx, page_path in enumerate(page_paths):
            items = ocr_image(ocr, page_path)
            for t, bbox in items:
                abs_y = page_idx * 10000 + (bbox[1] + bbox[3]) / 2
                all_items.append((t, bbox, page_idx, abs_y))
            print(f"  page {page_idx+1}: {len(items)} 段")

        politics = extract_per_candidate(all_items, names)
        imported = 0
        for n, text in politics.items():
            text = text.strip()
            cid = name_to_id[n]
            if not text or len(text) < 30:
                print(f"  - {n}: 過短 ({len(text)} 字)，略")
                continue
            ex = conn.execute(
                "SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=? AND seq=1",
                (cid, election_id),
            ).fetchone()
            if ex:
                print(f"  - {n}: 已存在")
                continue
            conn.execute(
                "INSERT INTO platforms (candidate_id, election_id, seq, title, content) "
                "VALUES (?, ?, 1, NULL, ?)",
                (cid, election_id, text),
            )
            conn.execute(
                "INSERT INTO platform_sources "
                "(candidate_id, election_id, source_type, local_path, description) "
                "VALUES (?, ?, 'page_ocr', ?, ?)",
                (cid, election_id, pdf_rel, "公報整頁 OCR"),
            )
            print(f"  + {n}: {len(text)} 字")
            imported += 1
        conn.commit()
        print(f"  ✓ 新增 {imported}")
        grand += imported

    print(f"\n總計新增 {grand} 條政見")
    conn.close()


if __name__ == "__main__":
    main()
