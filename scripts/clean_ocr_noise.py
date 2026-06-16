"""
清理 OCR 政見中混入的他人 bio 雜訊。

公報 PDF 是多欄式，OCR 按 y 切會把同一行不同人的「性別：」「出生年月日：」
「出生地：」等基本資料行混進政見內容。

策略：
  - 移除「性別：」「出生年月日：」「出生地：」開頭的整行
  - 移除「第N頁(共N頁)」等 footer
  - 移除短於 5 字的雜訊行
  - 保留實質政見內容

執行：
  python scripts/clean_ocr_noise.py [--dry-run]
"""
import argparse
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"

# 識別雜訊行的 patterns
NOISE_PATTERNS = [
    re.compile(r"^\s*性別\s*[：:]\s*[男女]\s*$"),
    re.compile(r"^\s*出生年月日\s*[：:]\s*[\d/\-]+\s*$"),
    re.compile(r"^\s*出生地\s*[：:]"),
    re.compile(r"^\s*第\s*\d+\s*頁\s*\(?共\s*\d+\s*頁\)?\s*$"),
    re.compile(r"^\s*基本資料\s*$"),
    re.compile(r"^\s*名單次序\s*$"),
    re.compile(r"^\s*號次\s*[·．]\s*名稱\s*$"),
    re.compile(r"^\s*學歷\s*$"),
    re.compile(r"^\s*經歷\s*$"),
    re.compile(r"^\s*姓名\s*$"),
    re.compile(r"^\s*政見\s*$"),
    re.compile(r"^\s*相\s*片\s*$"),
]


def clean_content(content: str) -> tuple[str, int]:
    """回傳 (clean_text, removed_count)"""
    lines = content.split("\n")
    cleaned = []
    removed = 0
    for line in lines:
        stripped = line.strip()
        if any(p.match(stripped) for p in NOISE_PATTERNS):
            removed += 1
            continue
        cleaned.append(line)
    return "\n".join(cleaned), removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--election-id", type=int, help="僅處理特定 election")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT p.platform_id, p.content, c.name, c.election_id
        FROM platforms p JOIN candidates c ON p.candidate_id=c.candidate_id
    """
    params: list = []
    if args.election_id:
        sql += " WHERE c.election_id = ?"
        params.append(args.election_id)

    rows = conn.execute(sql, params).fetchall()
    print(f"📋 {len(rows)} 條政見要清理")

    total_removed = 0
    affected = 0
    for r in rows:
        cleaned, removed = clean_content(r["content"])
        if removed > 0:
            total_removed += removed
            affected += 1
            if not args.dry_run:
                conn.execute(
                    "UPDATE platforms SET content=? WHERE platform_id=?",
                    (cleaned, r["platform_id"]),
                )

    if not args.dry_run:
        conn.commit()
    print(f"✓ {affected} 條政見有改動，共移除 {total_removed} 行雜訊")
    conn.close()


if __name__ == "__main__":
    main()
