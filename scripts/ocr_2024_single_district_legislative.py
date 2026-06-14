"""
2024 區域立委公報中，11 個單一選區縣市的 PDF（連江/金門/基隆/嘉義/
新竹/澎湖/臺東 etc.）沒有「第N選舉區」suffix，主流程跳過。
這個腳本顯式映射檔名 → district 後跑 OCR。

執行：
  python scripts/ocr_2024_single_district_legislative.py
"""
import sqlite3
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "db.sqlite"
OUT_DIR = ROOT / "data" / "bulletin_pages_legislators"

# (district, pdf 相對路徑)
JOBS = [
    ("臺東縣第01選區", "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員/17臺東縣/臺東縣區域立法委員選舉公報.pdf"),
    ("澎湖縣第01選區", "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員/18澎湖縣/澎湖縣區域立法委員選舉.pdf"),
    ("金門縣第01選區", "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員/19金門縣/金門縣選舉區.pdf"),
    ("連江縣第01選區", "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員/20連江縣/連江縣公報-立法委員.pdf"),
    ("基隆市第01選區", "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員/21基隆市/基隆市選舉區.pdf"),
    ("新竹市第01選區", "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員/22新竹市/01新竹市立委選舉.pdf"),
    ("嘉義市第01選區", "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員/23嘉義市/嘉義市立委選舉.pdf"),
    ("宜蘭縣第01選區", "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員/15宜蘭縣/宜蘭縣區域立法委員選舉公報.pdf"),
    ("花蓮縣第01選區", "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員/16花蓮縣/花蓮縣選舉區.pdf"),
    # 南投縣的 PDF 同時含第1+第2選區
    ("南投縣第01選區", "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員/11南投縣/南投縣立委第1.2選舉區.pdf"),
    ("南投縣第02選區", "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員/11南投縣/南投縣立委第1.2選舉區.pdf"),
]

ELECTION_ID = 51


def render_pages(pdf_path: Path, max_pages: int = 4, dpi: int = 200) -> list[Path]:
    doc = fitz.open(pdf_path)
    paths = []
    safe_stem = pdf_path.stem.replace("/", "_")
    for i in range(min(max_pages, doc.page_count)):
        out = OUT_DIR / f"single_{safe_stem}_p{i+1}.png"
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


def extract_per_candidate(all_items: list, names: list[str]) -> dict[str, str]:
    name_pos = {}
    for n in names:
        for t, _, _, abs_y in all_items:
            if t.strip() == n:
                name_pos[n] = abs_y
                break
        if n in name_pos:
            continue
        if len(n) >= 2:
            prefix = n[:2]
            for t, _, _, abs_y in all_items:
                tt = t.strip()
                if tt.startswith(prefix) and len(tt) <= len(n) + 8:
                    name_pos[n] = abs_y
                    break
    if not name_pos:
        return {n: "" for n in names}
    sorted_names = sorted(name_pos.items(), key=lambda x: x[1])
    max_y = max(item[3] for item in all_items) if all_items else 1e9
    result = {}
    for i, (n, y_start) in enumerate(sorted_names):
        y_end = sorted_names[i + 1][1] - 5 if i + 1 < len(sorted_names) else max_y
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
    # 按 PDF 分組，避免同個 PDF 跑兩次（南投兩個選區共用）
    by_pdf: dict[str, list[str]] = {}
    for district, pdf_rel in JOBS:
        by_pdf.setdefault(pdf_rel, []).append(district)

    for pdf_rel, districts in by_pdf.items():
        pdf = ROOT / pdf_rel
        if not pdf.exists():
            print(f"✗ {pdf} 不存在")
            continue
        print(f"\n=== {pdf.name} ===")
        print(f"  districts: {districts}")

        # 收集所有候選人（多個 district 合併）
        all_names_set = []
        all_name_to_id = {}
        all_missing = []
        for d in districts:
            rows = conn.execute(
                "SELECT DISTINCT c.candidate_id, c.name "
                "FROM election_results er JOIN candidates c ON er.candidate_id=c.candidate_id "
                "WHERE er.election_id=? AND er.district=?",
                (ELECTION_ID, d),
            ).fetchall()
            for r in rows:
                all_names_set.append(r["name"])
                all_name_to_id[r["name"]] = r["candidate_id"]
                ex = conn.execute(
                    "SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=?",
                    (r["candidate_id"], ELECTION_ID),
                ).fetchone()
                if not ex:
                    all_missing.append(r["name"])
        if not all_missing:
            print(f"  ✓ 全部已入庫，跳過")
            continue
        print(f"  缺政見：{all_missing}")

        page_paths = render_pages(pdf)
        all_items = []
        for page_idx, page_path in enumerate(page_paths):
            items = ocr_image(ocr, page_path)
            for t, bbox in items:
                abs_y = page_idx * 10000 + (bbox[1] + bbox[3]) / 2
                all_items.append((t, bbox, page_idx, abs_y))

        politics = extract_per_candidate(all_items, all_names_set)
        imported = 0
        for n in all_missing:
            text = (politics.get(n) or "").strip()
            cid = all_name_to_id[n]
            if not text or len(text) < 30:
                print(f"  - {n}: 過短 ({len(text)} 字)")
                continue
            conn.execute(
                "INSERT INTO platforms (candidate_id, election_id, seq, title, content) "
                "VALUES (?, ?, 1, NULL, ?)",
                (cid, ELECTION_ID, text),
            )
            conn.execute(
                "INSERT INTO platform_sources "
                "(candidate_id, election_id, source_type, local_path, description) "
                "VALUES (?, ?, 'page_ocr', ?, ?)",
                (cid, ELECTION_ID, pdf_rel, "單一選區公報 OCR"),
            )
            print(f"  + {n}: {len(text)} 字")
            imported += 1
        conn.commit()
        grand += imported

    print(f"\n總計新增 {grand} 條政見")
    conn.close()


if __name__ == "__main__":
    main()
