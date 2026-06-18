"""通用縣市長公報 OCR：直轄市長 + 縣市長 PDF → 縣市名 → 候選人。

用法：
  python scripts/ocr_mayoral_by_year.py 111 49   # 2022 縣市長 election_id=49
  python scripts/ocr_mayoral_by_year.py 107 42   # 2018
  python scripts/ocr_mayoral_by_year.py 103 33   # 2014

每個 PDF = 一個縣市。候選人 district = 縣市名。
"""
import re
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ocr_2024_single_district_legislative import (  # noqa
    render_pages,
    ocr_image,
    extract_per_candidate,
)

DB = ROOT / "data" / "db.sqlite"

COUNTIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市",
    "基隆市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣",
    "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣",
    "臺東縣", "澎湖縣", "金門縣", "連江縣",
    # 升格前舊名
    "臺北縣", "桃園縣", "臺中縣", "臺南縣", "高雄縣",
]


def county_from_filename(name: str) -> str | None:
    n = name.replace("台", "臺")
    # 去前綴數字
    n = re.sub(r"^\d+", "", n)
    for c in COUNTIES:
        if n.startswith(c) or c in n:
            return c
    return None


def main():
    year = int(sys.argv[1])
    election_id = int(sys.argv[2])

    pdf_roots = [
        ROOT / "data" / "bulletins" / "01選舉公報" / "03直轄市長" / f"{year:03d}年",
        ROOT / "data" / "bulletins" / "01選舉公報" / "04縣市長" / f"{year:03d}年",
    ]
    pdfs = []
    for r in pdf_roots:
        if r.exists():
            pdfs.extend(sorted(r.rglob("*.pdf")))
    if not pdfs:
        print(f"找不到 {year} 年公報"); return
    print(f"📂 {len(pdfs)} 個 PDF，election_id={election_id}")

    print("初始化 PaddleOCR…")
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    grand = 0

    for pdf in pdfs:
        county = county_from_filename(pdf.name)
        if not county:
            print(f"✗ 無法判縣市：{pdf.name}")
            continue
        # 候選人 district = 縣市名（可能含舊名）
        rows = conn.execute(
            "SELECT DISTINCT c.candidate_id, c.name "
            "FROM election_results er JOIN candidates c ON er.candidate_id=c.candidate_id "
            "WHERE er.election_id=? AND er.district=?",
            (election_id, county),
        ).fetchall()
        if not rows:
            print(f"✗ {county}: DB 無候選人 (election {election_id})")
            continue
        names = [r["name"] for r in rows]
        name_to_id = {r["name"]: r["candidate_id"] for r in rows}
        missing = [
            n for n in names
            if not conn.execute(
                "SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=?",
                (name_to_id[n], election_id),
            ).fetchone()
        ]
        if not missing:
            print(f"✓ {county}: 已全入庫")
            continue
        print(f"\n=== {county} ({pdf.name}) 缺 {missing} ===")

        page_paths = render_pages(pdf, max_pages=6)
        all_items = []
        for page_idx, page_path in enumerate(page_paths):
            for t, bbox in ocr_image(ocr, page_path):
                abs_y = page_idx * 10000 + (bbox[1] + bbox[3]) / 2
                all_items.append((t, bbox, page_idx, abs_y))

        politics = extract_per_candidate(all_items, names)
        for n in missing:
            text = (politics.get(n) or "").strip()
            if not text or len(text) < 30:
                print(f"  - {n}: 過短 ({len(text)} 字)")
                continue
            cid = name_to_id[n]
            conn.execute(
                "INSERT INTO platforms (candidate_id, election_id, seq, title, content) "
                "VALUES (?, ?, 1, NULL, ?)",
                (cid, election_id, text),
            )
            conn.execute(
                "INSERT INTO platform_sources "
                "(candidate_id, election_id, source_type, local_path, description) "
                "VALUES (?, ?, 'page_ocr', ?, ?)",
                (cid, election_id, str(pdf.relative_to(ROOT)), "縣市長公報 OCR"),
            )
            print(f"  + {n}: {len(text)} 字")
            grand += 1
        conn.commit()

    print(f"\n總計新增 {grand} 條政見")
    conn.close()


if __name__ == "__main__":
    main()
