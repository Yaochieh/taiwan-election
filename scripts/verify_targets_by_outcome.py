"""用「選舉結果」對承諾/政績做第一層查證。

這是最可靠、可程式化的查證維度：
- 承諾 (future)：
    - 候選人該選舉「落選」→ 此承諾未獲執政機會 → status='not_executed'
    - 候選人該選舉「當選」→ 進入任期可追蹤 → status='in_office'（待接公開資料）
- 政績 (past)：維持 pending（待考證），但若該選舉落選，標註此「政績」是
  競選時的自我宣稱、未經第三方驗證。

執行：python scripts/verify_targets_by_outcome.py [--dry-run]
"""
import argparse
import sqlite3
from datetime import date
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db.sqlite"


def candidate_won(conn, person: str, election_id: int) -> bool | None:
    """該人在該場選舉是否當選。None = 查不到。"""
    row = conn.execute(
        """SELECT MAX(er.elected) AS won
           FROM candidates c
           JOIN election_results er ON er.candidate_id = c.candidate_id
           WHERE c.name = ? AND c.election_id = ?""",
        (person, election_id),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return row[0] == 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT target_id, person_name, election_id, tense
        FROM platform_targets
        WHERE auto_extracted = 1 AND election_id IS NOT NULL
    """).fetchall()
    counts = {"not_executed": 0, "in_office": 0, "self_claim": 0, "pending": 0, "skip": 0}
    today = date.today().isoformat()
    for r in rows:
        won = candidate_won(conn, r["person_name"], r["election_id"])
        if won is None:
            counts["skip"] += 1
            continue
        tense = r["tense"]
        status = None
        note = None
        if tense == "future":
            if won:
                status = "in_office"
                note = "候選人當選，握有執政/問政機會，可對照任內表現查證"
                counts["in_office"] += 1
            else:
                status = "not_executed"
                note = "候選人於該選舉未當選，此承諾未獲執政機會"
                counts["not_executed"] += 1
        elif tense == "past":
            if won:
                status = "pending"
                note = "競選時宣稱之政績，待公開資料查證"
                counts["pending"] += 1
            else:
                status = "self_claim"
                note = "落選候選人競選時自我宣稱之政績，未經第三方驗證"
                counts["self_claim"] += 1
        else:
            counts["skip"] += 1
            continue
        if not args.dry_run:
            conn.execute(
                "UPDATE platform_targets SET verification_status=?, verification_note=? WHERE target_id=?",
                (status, note, r["target_id"]),
            )
    if not args.dry_run:
        conn.commit()
    print("查證統計：")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    conn.close()


if __name__ == "__main__":
    main()
