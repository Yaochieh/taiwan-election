"""
從公報 PDF 抽取候選人大頭照。

照片特徵：
  - 寬度約 110-200pt（直式相片）
  - 高/寬比 1.0 - 1.5（直式人像）
  - 位於候選人姓名附近

策略：
  1. 用 DB 候選人姓名作為錨點（與 extract_bulletin_images 共用）
  2. 找姓名 column 中的小圖（窄高比）
  3. 用 DPI=200 截圖存到 data/candidate_photos/{election_id}/{name}.png
  4. 更新 candidates.photo_path

執行：
  python scripts/extract_candidate_photos.py --pdf <pdf> --election-id 49 --district "地區(63, 0, 0)"
  python scripts/extract_candidate_photos.py --bulk   # 全部 6 都市長 + 立委
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "data" / "candidate_photos"
DPI = 200

# 照片尺寸範圍（pt）
MIN_W, MAX_W = 80, 230
MIN_H, MAX_H = 100, 250

DB_PATH = ROOT / "data" / "db.sqlite"


def ensure_schema():
    """在 candidates 表加上 photo_path 欄位（若尚未存在）。"""
    conn = sqlite3.connect(DB_PATH)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(candidates)")]
    if "photo_path" not in cols:
        conn.execute("ALTER TABLE candidates ADD COLUMN photo_path TEXT")
        conn.commit()
        print("✓ 新增 candidates.photo_path 欄位")
    conn.close()


def find_name_anchors(page, names):
    """跟 extract_bulletin_images / parse_bulletin_v2 共用：找姓名短 block。"""
    import re
    blocks = page.get_text("blocks")
    anchors = {}
    for name in names:
        # 短 block 優先
        for b in blocks:
            text = b[4]
            if name in text and len(text.strip()) < 30:
                anchors[name] = b[:4]
                break
        # fallback search_for
        if name not in anchors:
            rects = page.search_for(name)
            if rects:
                r = rects[0]
                anchors[name] = (r.x0, r.y0, r.x1, r.y1)
    return anchors


def find_photo_for(page, name_anchor, max_distance: float = 400):
    """在姓名 anchor 附近找小相片。"""
    nx0, ny0, nx1, ny1 = name_anchor

    candidates = []
    for img in page.get_image_info():
        bbox = img.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        x0, y0, x1, y1 = bbox
        w = x1 - x0
        h = y1 - y0

        # 尺寸過濾
        if not (MIN_W <= w <= MAX_W and MIN_H <= h <= MAX_H):
            continue
        # 比例必須直式（高 > 寬）或近正方形
        ratio = h / w if w > 0 else 0
        if not (0.85 <= ratio <= 2.0):
            continue

        # 與姓名距離（X 接近 + Y 在姓名上下方）
        x_center = (x0 + x1) / 2
        y_center = (y0 + y1) / 2
        name_x_center = (nx0 + nx1) / 2
        name_y_center = (ny0 + ny1) / 2

        # X 軸：姓名在照片左/右邊界 100pt 內
        if abs(x_center - name_x_center) > 200:
            continue
        # Y 軸：照片應該與姓名同一候選人區塊內（距離 < max_distance）
        if abs(y_center - name_y_center) > max_distance:
            continue

        # 距離當分數
        dist = abs(x_center - name_x_center) + abs(y_center - name_y_center)
        candidates.append((dist, bbox))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def extract_pdf(pdf_path: Path, election_id: int, names: list[str],
                max_pages: int = 2, dry_run: bool = False) -> dict[str, str]:
    """跑單一 PDF，回傳 {name: relative_path}。"""
    doc = fitz.open(pdf_path)
    results: dict[str, str] = {}
    pages_to_scan = min(doc.page_count, max_pages)

    for p_idx in range(pages_to_scan):
        page = doc[p_idx]
        anchors = find_name_anchors(page, names)
        for name, anchor in anchors.items():
            if name in results:
                continue
            bbox = find_photo_for(page, anchor)
            if not bbox:
                continue
            if dry_run:
                results[name] = "(dry-run)"
                continue

            safe = name.replace("/", "_").replace(" ", "_")
            out_path = OUT_DIR / str(election_id) / f"{safe}.png"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            pix = page.get_pixmap(clip=fitz.Rect(*bbox), dpi=DPI)
            pix.save(out_path)
            results[name] = str(out_path.relative_to(ROOT))

    return results


def update_db(results: dict[str, str], election_id: int):
    if not results:
        return
    conn = sqlite3.connect(DB_PATH)
    updated = 0
    for name, path in results.items():
        if path == "(dry-run)":
            continue
        r = conn.execute(
            "UPDATE candidates SET photo_path = ? "
            "WHERE election_id = ? AND name = ?",
            (path, election_id, name),
        )
        updated += r.rowcount
    conn.commit()
    conn.close()
    if updated:
        print(f"  → 更新 {updated} 筆 candidates.photo_path")


def get_db_names(election_id: int, district: str | None = None) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if district:
        rows = conn.execute("""
            SELECT DISTINCT c.name FROM election_results er
            JOIN candidates c ON er.candidate_id = c.candidate_id
            WHERE er.election_id = ? AND er.district = ?
        """, (election_id, district)).fetchall()
    else:
        rows = conn.execute(
            "SELECT name FROM candidates WHERE election_id = ?",
            (election_id,),
        ).fetchall()
    conn.close()
    return [r["name"] for r in rows]


def bulk_run(dry_run: bool = False):
    """批次跑 2022 6 都市長 + 2024 立委 + 2024 不分區（如可）。"""
    ensure_schema()

    # 2022 6 都市長 (election_id=49)
    mayor_districts = {
        "臺北市": ("地區(63, 0, 0)", 49, "111年"),
        "新北市": ("地區(65, 0, 0)", 49, "111年"),
        "桃園市": ("地區(68, 0, 0)", 49, "111年"),
        "臺中市": ("地區(66, 0, 0)", 49, "111年"),
        "台南市": ("地區(67, 0, 0)", 49, "111年"),
        "高雄市": ("地區(64, 0, 0)", 49, "111年"),
    }
    bulletin_root = ROOT / "data/bulletins/01選舉公報/03直轄市長"

    total = 0
    for city, (district, eid, year) in mayor_districts.items():
        pdf_path = bulletin_root / year / f"{city}市長.pdf"
        if not pdf_path.exists():
            print(f"  ✗ {city}：找不到 PDF")
            continue
        names = get_db_names(eid, district)
        results = extract_pdf(pdf_path, eid, names, dry_run=dry_run)
        update_db(results, eid)
        print(f"  ✓ {city}：找到 {len(results)} / {len(names)} 張照片")
        total += len(results)

    # 2024 立委 — 73 個區域
    leg_root = ROOT / "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員"
    if leg_root.exists():
        import re
        # 跟 import_legislative 路徑解析共用
        sys.path.insert(0, str(ROOT))
        from scripts.import_legislative_platforms import (
            parse_district_from_path,
            db_district_for,
            ELECTION_REGIONAL,
        )
        pdfs = sorted(p for p in leg_root.glob("**/*.pdf") if "投開票所" not in p.name and "罷免" not in p.name)
        print(f"\n  立委公報：{len(pdfs)} 個 PDF")
        for pdf in pdfs:
            city, region = parse_district_from_path(pdf)
            district = db_district_for(city, region)
            if not district:
                continue
            names = get_db_names(ELECTION_REGIONAL, district)
            results = extract_pdf(pdf, ELECTION_REGIONAL, names, dry_run=dry_run)
            update_db(results, ELECTION_REGIONAL)
            if results:
                total += len(results)

    print(f"\n✓ 共抽取 {total} 張候選人照片")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf")
    ap.add_argument("--election-id", type=int)
    ap.add_argument("--district")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--bulk", action="store_true")
    args = ap.parse_args()

    if args.bulk:
        bulk_run(dry_run=args.dry_run)
        return

    if not args.pdf or not args.election_id:
        ap.error("--pdf 和 --election-id 必須提供（或用 --bulk）")

    ensure_schema()
    names = get_db_names(args.election_id, args.district)
    print(f"📋 {Path(args.pdf).name}：目標 {len(names)} 位候選人")
    results = extract_pdf(Path(args.pdf), args.election_id, names, dry_run=args.dry_run)
    update_db(results, args.election_id)
    print(f"\n✓ 找到 {len(results)} 張照片")


if __name__ == "__main__":
    main()
