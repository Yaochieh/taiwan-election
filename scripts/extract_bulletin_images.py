"""
從公報 PDF 抽取候選人的「圖片版政見」。

許多主要候選人會用設計過的圖片提交政見（含口號、視覺設計）；
這些政見以圖片嵌入 PDF，文字解析會抓不到內容。

策略：
  1. 對每位候選人，用姓名 anchor 找其區塊範圍
  2. 在該區塊內找寬幅圖片（>=300pt 寬）視為政見圖
  3. 排除頭像（窄高比、約 110x140pt）
  4. 高解析度截圖保存到 data/bulletin_images/{election_id}/{candidate}.png
  5. 寫入 platform_sources 記錄（source_type=image_platform）

用法：
  python scripts/extract_bulletin_images.py --pdf <pdf> --election-id 49 --district "..."
"""
import argparse
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "data" / "bulletin_images"
PHOTO_MAX_WIDTH = 250    # 候選人頭像 < 250pt 寬
POLITICS_MIN_WIDTH = 300  # 政見圖 >= 300pt 寬
DPI = 200                # 截圖解析度


def find_name_anchors(page, names):
    """從 page 找姓名（與 v2 parser 共用邏輯）。"""
    blocks = page.get_text("blocks")
    anchors = {}
    for name in names:
        for b in blocks:
            text = b[4]
            if name in text and len(text.strip()) < 30:
                anchors[name] = b[:4]
                break
        if name not in anchors:
            rects = page.search_for(name)
            if rects:
                r = rects[0]
                anchors[name] = (r.x0, r.y0, r.x1, r.y1)
    return anchors


def extract_for_candidate(page, name, anchor, all_anchors_y, max_distance=600):
    """找此候選人區塊內的政見圖。回傳 [(bbox, pix), ...]"""
    nx0, ny0, nx1, ny1 = anchor

    # 該候選人區塊的 y 上限
    next_y = min(
        (y for y in all_anchors_y if y > ny0 + 200),
        default=ny0 + max_distance,
    )
    upper_bound = min(next_y, ny0 + max_distance)

    img_info = page.get_image_info()
    matched = []
    for img in img_info:
        bbox = img.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        x0, y0, x1, y1 = bbox
        width = x1 - x0
        # 政見圖：寬度 >= 300pt
        if width < POLITICS_MIN_WIDTH:
            continue
        # 必須在姓名下方
        if y1 < ny0 + 50:
            continue
        # 不超過該候選人區塊
        if y0 > upper_bound:
            continue
        # X 軸要與姓名 column 重疊（寬鬆 100px）
        if x1 < nx0 - 100 or x0 > nx1 + 100:
            continue
        matched.append((x0, y0, x1, y1))

    # 對每個 bbox 截圖
    pixmaps = []
    for bbox in matched:
        clip = fitz.Rect(*bbox)
        pix = page.get_pixmap(clip=clip, dpi=DPI)
        pixmaps.append((bbox, pix))
    return pixmaps


def extract_pdf(pdf_path: Path, election_id: int, names: list[str],
                max_pages: int = 1, dry_run: bool = False):
    doc = fitz.open(pdf_path)
    out_subdir = OUT_DIR / str(election_id)

    results = {}  # name -> list of saved paths
    pages_to_scan = min(doc.page_count, max_pages)

    for p_idx in range(pages_to_scan):
        page = doc[p_idx]
        anchors = find_name_anchors(page, names)
        all_y = [v[1] for v in anchors.values()]

        for name, anchor in anchors.items():
            if results.get(name):
                continue  # 已處理
            pixmaps = extract_for_candidate(page, name, anchor, all_y)
            if not pixmaps:
                continue

            results.setdefault(name, [])
            for idx, (bbox, pix) in enumerate(pixmaps, 1):
                if dry_run:
                    print(f"  [dry-run] {name} #{idx}: bbox {bbox}, {pix.width}x{pix.height}")
                    results[name].append(None)
                    continue

                # 安全檔名：候選人姓名可能有 / 等字元
                safe_name = name.replace("/", "_").replace(" ", "_")
                out_path = out_subdir / f"{safe_name}_{idx}.png"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                pix.save(out_path)
                rel = out_path.relative_to(ROOT)
                results[name].append(str(rel))
                print(f"  ✓ {name} #{idx} → {rel}")

    return results


def update_db(results: dict, election_id: int, source_url: str | None = None):
    """把結果寫入 platform_sources（source_type=image_platform）。
    僅刪除這次處理到的候選人記錄，不影響其他候選人。"""
    from db.queries import get_connection

    with get_connection() as conn:
        # 移除這次處理到的候選人的 image_platform 記錄
        names_with_images = [n for n, paths in results.items() if paths and paths[0]]
        for name in names_with_images:
            conn.execute("""
                DELETE FROM platform_sources
                WHERE election_id = ? AND source_type = 'image_platform'
                  AND candidate_id IN (
                    SELECT candidate_id FROM candidates
                    WHERE election_id = ? AND name = ?
                  )
            """, (election_id, election_id, name))

        inserted = 0
        for name, paths in results.items():
            if not paths or paths[0] is None:
                continue
            row = conn.execute("""
                SELECT candidate_id FROM candidates
                WHERE election_id = ? AND name = ?
            """, (election_id, name)).fetchone()
            if not row:
                print(f"  ⚠️  DB 找不到候選人「{name}」")
                continue
            cid = row["candidate_id"]

            for path in paths:
                conn.execute("""
                    INSERT INTO platform_sources
                        (candidate_id, election_id, source_type, url, local_path, description, fetched_at)
                    VALUES (?, ?, 'image_platform', ?, ?, ?, datetime('now'))
                """, (
                    cid, election_id, source_url, path,
                    "候選人提交之圖片版政見（自中選會公報擷取）",
                ))
                inserted += 1
        conn.commit()
        print(f"\n✓ 寫入 {inserted} 筆 image_platform 來源紀錄")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--election-id", type=int, required=True)
    ap.add_argument("--district", help="限定 DB 候選人選區")
    ap.add_argument("--names", help="或直接指定候選人姓名（逗號分隔）")
    ap.add_argument("--source-url", help="原始公報 URL")
    ap.add_argument("--max-pages", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.names:
        names = [n.strip() for n in args.names.split(",")]
    else:
        from db.queries import get_connection
        with get_connection() as conn:
            if args.district:
                rows = conn.execute("""
                    SELECT DISTINCT c.name FROM election_results er
                    JOIN candidates c ON er.candidate_id = c.candidate_id
                    WHERE er.election_id = ? AND er.district = ?
                """, (args.election_id, args.district)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT name FROM candidates WHERE election_id = ?
                """, (args.election_id,)).fetchall()
            names = [r["name"] for r in rows]

    print(f"📋 處理 {Path(args.pdf).name}，目標 {len(names)} 位候選人")
    results = extract_pdf(Path(args.pdf), args.election_id, names,
                          max_pages=args.max_pages, dry_run=args.dry_run)
    if not args.dry_run:
        update_db(results, args.election_id, args.source_url)

    print(f"\n結果：{sum(1 for v in results.values() if v)} 位候選人有圖片政見")


if __name__ == "__main__":
    main()
