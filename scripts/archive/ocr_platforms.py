"""
用 PaddleOCR 把政見圖檔轉成可搜尋文字，存入 DB。

平台不在雲端跑 OCR（太慢且耗資源），改在本機跑、結果一次性入庫。

Schema：
  platform_sources 表新增 ocr_text 欄位（TEXT）

執行：
  python scripts/ocr_platforms.py --election-id 49 --district "地區(63, 0, 0)"  # 試跑 2022 台北市長
  python scripts/ocr_platforms.py --election-id 49                              # 整場 2022 縣市長
  python scripts/ocr_platforms.py --all                                          # 全部圖片
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "db.sqlite"


def ensure_schema(conn: sqlite3.Connection):
    """確保 platform_sources 表有 ocr_text 欄位。"""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(platform_sources)")]
    if "ocr_text" not in cols:
        conn.execute("ALTER TABLE platform_sources ADD COLUMN ocr_text TEXT")
        conn.commit()
        print("✓ 新增 ocr_text 欄位")


def ocr_one(ocr, image_path: Path) -> str:
    """對單張圖片跑 OCR，回傳完整文字（按行分隔）。"""
    result = ocr.predict(str(image_path))
    if not result:
        return ""
    # result 格式：list[dict]，每張影像一個 dict
    lines = []
    for page in result:
        # 試 PaddleOCR 3.x dict 結構
        if isinstance(page, dict):
            texts = page.get("rec_texts", [])
            scores = page.get("rec_scores", [])
            for t, s in zip(texts, scores):
                if s and s > 0.5:
                    lines.append(t)
        # 舊版 list[list] 結構
        elif isinstance(page, list):
            for line_block in page:
                if not line_block:
                    continue
                if isinstance(line_block, list) and len(line_block) >= 2:
                    text_info = line_block[1]
                    if isinstance(text_info, tuple):
                        text, confidence = text_info
                    elif isinstance(text_info, list):
                        text, confidence = text_info[0], text_info[1]
                    else:
                        continue
                    if confidence and confidence > 0.5:
                        lines.append(text)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--election-id", type=int)
    ap.add_argument("--district")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--overwrite", action="store_true", help="重新 OCR 已處理的")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    where = ["source_type = 'image_platform'", "local_path IS NOT NULL"]
    params: list = []
    if not args.overwrite:
        where.append("(ocr_text IS NULL OR ocr_text = '')")
    if args.election_id:
        where.append("election_id = ?")
        params.append(args.election_id)
    if args.district:
        where.append("""
            candidate_id IN (
                SELECT er.candidate_id FROM election_results er
                WHERE er.election_id = platform_sources.election_id
                  AND er.district = ?
            )
        """)
        params.append(args.district)

    rows = conn.execute(
        f"SELECT source_id, candidate_id, election_id, local_path FROM platform_sources "
        f"WHERE {' AND '.join(where)} ORDER BY source_id",
        params,
    ).fetchall()
    print(f"📋 待處理：{len(rows)} 張圖片")

    if not rows:
        print("沒有圖片需要 OCR")
        return

    # 初始化 PaddleOCR（中文）
    print("初始化 PaddleOCR（首次會下載 model）...")
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(use_textline_orientation=True, lang="ch")

    for idx, r in enumerate(rows, 1):
        img_path = ROOT / r["local_path"]
        if not img_path.exists():
            print(f"  ⚠️  [{idx}/{len(rows)}] 檔案不存在：{img_path}")
            continue

        # 取候選人姓名（給 log）
        cand_name = conn.execute(
            "SELECT name FROM candidates WHERE candidate_id = ?",
            (r["candidate_id"],),
        ).fetchone()
        name = cand_name["name"] if cand_name else f"id={r['candidate_id']}"

        print(f"  [{idx}/{len(rows)}] {name}：", end="", flush=True)
        try:
            text = ocr_one(ocr, img_path)
        except Exception as e:
            print(f" ✗ {e}")
            continue

        if not text:
            print(" (無文字)")
            continue

        conn.execute(
            "UPDATE platform_sources SET ocr_text = ? WHERE source_id = ?",
            (text, r["source_id"]),
        )
        conn.commit()
        print(f" ✓ {len(text)} 字")

    conn.close()
    print()
    print("✓ 完成")


if __name__ == "__main__":
    main()
