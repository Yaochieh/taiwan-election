"""複驗 8 條剛救回、重疊度 <60% 的政見：對完整頁面 OCR 重新計算重疊度。

原因：content_raw 只存了 full[:8000]（開頭是公報表頭），政見在 8000 字後被截掉。
- 對完整 OCR 重疊 >= 80% → 通過，content_raw 更新為完整 OCR（截 20000 字內含政見段）
- 仍 < 80% → 刪除該 platform（腦補疑慮，寧缺勿假）
"""
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from scripts.ocr_2024_single_district_legislative import render_pages, ocr_image  # noqa

DB = ROOT / "data" / "db.sqlite"
PIDS = [2683, 2685, 2692, 2701, 2702, 2703, 2704, 2706]


def overlap(text, source):
    t = re.sub(r"[\s\d。，、：（）()【】「」\.]", "", text)
    s = re.sub(r"[\s\d。，、：（）()【】「」\.]", "", source)
    if len(t) < 4:
        return 0.0
    grams = [t[i:i+4] for i in range(len(t) - 3)]
    return sum(1 for g in grams if g in s) / len(grams)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")
    kept = removed = 0
    for pid in PIDS:
        row = conn.execute(
            "SELECT p.platform_id, p.content, p.candidate_id, p.election_id, c.name, "
            "(SELECT ps.local_path FROM platform_sources ps WHERE ps.candidate_id=p.candidate_id "
            " AND ps.election_id=p.election_id AND ps.source_type='page_ocr' LIMIT 1) AS pdf "
            "FROM platforms p JOIN candidates c ON p.candidate_id=c.candidate_id "
            "WHERE p.platform_id=?", (pid,)).fetchone()
        if not row or not row["pdf"]:
            print(f"✗ {pid}: 找不到 PDF");
            continue
        pages = render_pages(ROOT / row["pdf"], max_pages=8)
        items = []
        for pi, pp in enumerate(pages):
            for txt, bbox in ocr_image(ocr, pp):
                items.append((pi, bbox[1], txt))
        items.sort(key=lambda x: (x[0], x[1]))
        full = "\n".join(t for _, _, t in items)
        ratio = overlap(row["content"], full)
        if ratio >= 0.80:
            conn.execute("UPDATE platforms SET content_raw=? WHERE platform_id=?",
                         (full[:20000], pid))
            conn.commit()
            print(f"✓ {pid} {row['name']}: 完整OCR重疊 {ratio:.0%} → 通過，raw 更新為完整 OCR")
            kept += 1
        else:
            conn.execute("DELETE FROM platform_targets WHERE source_platform_id=?", (pid,))
            conn.execute("DELETE FROM platforms WHERE platform_id=?", (pid,))
            conn.commit()
            print(f"✗ {pid} {row['name']}: 完整OCR重疊 {ratio:.0%} < 80% → 刪除")
            removed += 1
    conn.close()
    print(f"\n通過 {kept}、刪除 {removed}")


if __name__ == "__main__":
    main()
