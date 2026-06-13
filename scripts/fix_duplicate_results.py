"""
清理 election_results 中的重複資料（補選/重行選舉的 idempotency bug）。

策略：對於同 (election_id, candidate_id, district)，保留 result_id 最小那筆。

執行：
  python scripts/fix_duplicate_results.py --dry-run
  python scripts/fix_duplicate_results.py
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 找重複，保留 MIN(result_id)
    dups = conn.execute("""
        SELECT election_id, candidate_id, IFNULL(district, '') AS district,
               MIN(result_id) AS keep_id,
               COUNT(*) AS cnt
        FROM election_results
        GROUP BY election_id, candidate_id, IFNULL(district, '')
        HAVING COUNT(*) > 1
    """).fetchall()
    print(f"找到 {len(dups)} 組重複")

    total_to_delete = 0
    for d in dups:
        # 列出要刪的 id
        del_ids = conn.execute("""
            SELECT result_id FROM election_results
            WHERE election_id = ? AND candidate_id = ?
              AND IFNULL(district, '') = ?
              AND result_id != ?
        """, (d["election_id"], d["candidate_id"], d["district"], d["keep_id"])).fetchall()
        total_to_delete += len(del_ids)
        if args.dry_run:
            print(f"  [dry] election={d['election_id']} cand={d['candidate_id']} "
                  f"district={d['district']}：保留 {d['keep_id']}, 刪除 {len(del_ids)}")
            continue
        conn.executemany(
            "DELETE FROM election_results WHERE result_id = ?",
            [(r["result_id"],) for r in del_ids],
        )

    if args.dry_run:
        print(f"\n[dry-run] 共需刪除 {total_to_delete} 筆")
    else:
        conn.commit()
        print(f"\n✓ 已刪除 {total_to_delete} 筆重複資料")

    conn.close()


if __name__ == "__main__":
    main()
