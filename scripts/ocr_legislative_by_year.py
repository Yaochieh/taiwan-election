"""通用版區域立委公報 OCR：接受民國年份參數。

用法：
  python scripts/ocr_legislative_by_year.py 109   # 2020 第10屆
  python scripts/ocr_legislative_by_year.py 105   # 2016 第9屆

  python scripts/ocr_legislative_by_year.py 109 --type 山地原住民
  python scripts/ocr_legislative_by_year.py 109 --type 平地原住民
  python scripts/ocr_legislative_by_year.py 109 --type 不分區

預設處理「區域立法委員」。其他類型用 --type。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# 重用 2024 版的渲染與抽取邏輯
from scripts.ocr_2024_regional_legislative import (  # noqa
    render_pages,
    ocr_image,
    parse_district_from_path,
    extract_per_candidate,
)
import sqlite3

DB = ROOT / "data" / "db.sqlite"

# 民國年 → 中選會屆數 + 西元年
YEAR_INFO = {
    105: {"term": 9, "ad": 2016, "date": "2016-01-16"},
    109: {"term": 10, "ad": 2020, "date": "2020-01-11"},
    113: {"term": 11, "ad": 2024, "date": "2024-01-13"},
}

# type → 資料夾代號 + DB description
TYPE_INFO = {
    "區域": {"folder": "02區域立法委員", "desc": "區域"},
    "不分區": {"folder": "05全國不分區及僑居國外國民立法委員", "desc": "不分區政黨"},
    "山地原住民": {"folder": "04山地原住民立法委員", "desc": "山地原住民"},
    "平地原住民": {"folder": "03平地原住民立法委員", "desc": "平地原住民"},
}


def find_election_id(conn, date_str: str, desc: str) -> int | None:
    row = conn.execute(
        "SELECT election_id FROM elections "
        "WHERE date=? AND type='legislative' AND description=?",
        (date_str, desc),
    ).fetchone()
    return row[0] if row else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", type=int, help="民國年（105 / 109 / 113）")
    ap.add_argument("--type", default="區域", choices=list(TYPE_INFO))
    args = ap.parse_args()

    year_info = YEAR_INFO.get(args.year)
    if not year_info:
        print(f"未知年份 {args.year}"); return
    type_info = TYPE_INFO[args.type]
    pdf_root = ROOT / "data" / "bulletins" / "01選舉公報" / "02立法委員" \
               / f"{args.year:03d}年第{year_info['term']}屆" / type_info["folder"]
    if not pdf_root.exists():
        print(f"找不到目錄：{pdf_root}"); return

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    eid = find_election_id(conn, year_info["date"], type_info["desc"])
    if not eid:
        print(f"DB 找不到 election (date={year_info['date']} desc={type_info['desc']})"); return
    print(f"📋 election_id={eid}, 屆={year_info['term']}, 類型={args.type}")
    print(f"📂 PDF 來源：{pdf_root}")

    print("初始化 PaddleOCR…")
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")

    pdf_files = sorted(pdf_root.rglob("*.pdf"))
    print(f"找到 {len(pdf_files)} 個 PDF")

    grand = 0
    for pdf in pdf_files:
        district = parse_district_from_path(pdf) if args.type == "區域" else None
        if args.type == "區域" and not district:
            print(f"  ✗ 無法解析 district：{pdf.name}")
            continue

        # 找該選區候選人
        if args.type == "區域":
            rows = conn.execute(
                "SELECT DISTINCT c.candidate_id, c.name "
                "FROM election_results er JOIN candidates c ON er.candidate_id=c.candidate_id "
                "WHERE er.election_id=? AND er.district=?",
                (eid, district),
            ).fetchall()
        else:
            # 不分區/原住民：撈全部候選人
            rows = conn.execute(
                "SELECT candidate_id, name FROM candidates WHERE election_id=?",
                (eid,),
            ).fetchall()
        names = [r["name"] for r in rows]
        name_to_id = {r["name"]: r["candidate_id"] for r in rows}
        if not names:
            print(f"  ✗ {district or pdf.name}: DB 無候選人")
            continue

        missing = [n for n in names if not conn.execute(
            "SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=?",
            (name_to_id[n], eid),
        ).fetchone()]
        if not missing:
            print(f"  ✓ {district or pdf.name}: 已全部入庫")
            continue

        print(f"\n=== {district or pdf.name} ===")
        print(f"  缺政見 {len(missing)}：{missing[:5]}{'...' if len(missing)>5 else ''}")

        page_paths = render_pages(pdf)
        all_items = []
        for page_idx, page_path in enumerate(page_paths):
            items = ocr_image(ocr, page_path)
            for t, bbox in items:
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
                (cid, eid, text),
            )
            conn.execute(
                "INSERT INTO platform_sources "
                "(candidate_id, election_id, source_type, local_path, description) "
                "VALUES (?, ?, 'page_ocr', ?, ?)",
                (cid, eid, str(pdf.relative_to(ROOT)), "公報整頁 OCR"),
            )
            print(f"  + {n}: {len(text)} 字")
            grand += 1
        conn.commit()

    print(f"\n總計新增 {grand} 條政見")
    conn.close()


if __name__ == "__main__":
    main()
