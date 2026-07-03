"""
對 OCR 後變成「一條超長 content 但裡面有 1./2./3./一、二、三、●...」
這種已內含條列結構的 platforms，自動拆成多條 seq。

策略：
- 找 content 開頭或換行後出現 `\d+[.、)]\s` 或 `[一二三四五六七八九十]+、` 或 `●`
- 用 regex 切，每段成為新 seq
- 保留 source_url / note 不變
- 在 note 加 [自動拆條 by Claude YYYY-MM-DD]

執行：python scripts/split_multi_bullet_platforms.py
"""
import re
import sqlite3
from datetime import date
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db.sqlite"

# split pattern: 1. 1、 (1) 1) 一、 ●開頭新段
SPLIT_RE = re.compile(
    r"(?:^|\n)\s*"
    r"(?:"
    r"\d+[\.、)）]\s+"
    r"|[一二三四五六七八九十百]+、\s*"
    r"|[●○■□▪▫]\s+"
    r")"
)

TODAY = date.today().isoformat()
TAG = f"[自動拆條 by Claude {TODAY}]"


def split_content(content: str) -> list[str]:
    # split by pattern but keep delimiter
    parts = SPLIT_RE.split(content)
    # 至少要切出 4 段才有意義
    if len(parts) < 4:
        return []
    out = []
    for p in parts:
        p = p.strip()
        if len(p) < 12:  # 過短
            continue
        if len(p) > 600:  # 過長（沒切乾淨）
            continue
        out.append(p)
    return out if len(out) >= 3 else []


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    # 條件：單筆 content 很長 (>=400)，且 sibling 條數 <= 2
    rows = conn.execute("""
        SELECT p.platform_id, p.candidate_id, p.election_id, p.seq,
               p.content, p.source_url, p.note,
               (SELECT COUNT(*) FROM platforms p2
                WHERE p2.candidate_id=p.candidate_id AND p2.election_id=p.election_id) AS sibling_n
        FROM platforms p
        WHERE length(p.content) >= 400
          AND (p.note IS NULL OR p.note NOT LIKE '%人工潤稿%')
    """).fetchall()

    total_processed = 0
    total_new = 0
    for r in rows:
        if r["sibling_n"] > 2:
            continue
        bullets = split_content(r["content"])
        if not bullets:
            continue
        # 開始 transaction：刪原 row、插入多條
        cur = conn.cursor()
        # 保留 content_raw
        original_raw = conn.execute(
            "SELECT content_raw FROM platforms WHERE platform_id=?",
            (r["platform_id"],),
        ).fetchone()["content_raw"] or r["content"]
        cur.execute("DELETE FROM platforms WHERE platform_id=?", (r["platform_id"],))
        for i, body in enumerate(bullets, start=1):
            existing_note = r["note"] or ""
            new_note = (existing_note + " · " + TAG) if existing_note else TAG
            cur.execute(
                """INSERT INTO platforms
                   (candidate_id, election_id, seq, content, content_raw,
                    source_url, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (r["candidate_id"], r["election_id"], i, body,
                 original_raw if i == 1 else None,
                 r["source_url"], new_note),
            )
        total_processed += 1
        total_new += len(bullets)
    conn.commit()
    print(f"✓ 處理 {total_processed} 條原始 platforms → 拆成 {total_new} 條")
    conn.close()


if __name__ == "__main__":
    main()
