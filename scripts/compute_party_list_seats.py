"""
計算不分區立委各政黨席次，並更新 election_results.elected。

台灣政黨比例代表制規則（《公職人員選舉罷免法》§67）：
  1. 政黨得票率須達 5%（門檻）
  2. 依 Hare quota（黑爾配額）分配基本席次：
       quota = 門檻政黨總票數 / 總席次
       基本席次 = floor(政黨票數 / quota)
  3. 剩餘席次依各黨餘數由大到小分配（最大餘數法）

席次總數：
  - 2008 年起（第7屆立委以後）：34 席
  - 2004 年前（第6屆立委以前）：41 席

用法：
  python scripts/compute_party_list_seats.py
  python scripts/compute_party_list_seats.py --dry-run
"""

import argparse
import math
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "db.sqlite"

# 2008-01-12 起實施新選制（34 席）
NEW_SYSTEM_CUTOFF = "2008-01-01"
SEATS_NEW = 34
SEATS_OLD = 41
THRESHOLD = 0.05


def allocate_seats(party_votes: dict[int, int], total_seats: int) -> dict[int, int]:
    """
    Hare quota + 最大餘數法分配席次。

    :param party_votes: {candidate_id: votes}（只含通過門檻的政黨）
    :param total_seats: 總席次
    :return: {candidate_id: seats}
    """
    qualifying_total = sum(party_votes.values())
    if qualifying_total == 0:
        return {}

    quota = qualifying_total / total_seats

    # 基本席次（floor）+ 餘數
    base: dict[int, int] = {}
    remainder: dict[int, float] = {}
    for cid, votes in party_votes.items():
        exact = votes / quota
        base[cid] = math.floor(exact)
        remainder[cid] = exact - base[cid]

    # 剩餘席次數量
    remaining = total_seats - sum(base.values())

    # 按餘數由大到小排序，同餘數再按 candidate_id 穩定排序
    ranked = sorted(party_votes.keys(), key=lambda cid: (-remainder[cid], cid))
    for cid in ranked[:remaining]:
        base[cid] += 1

    return base


def process_election(conn: sqlite3.Connection, election_id: int,
                     election_date: str, dry_run: bool) -> None:
    total_seats = SEATS_NEW if election_date >= NEW_SYSTEM_CUTOFF else SEATS_OLD

    # 取得本次不分區選舉所有政黨票數（election_results 的 candidate_id = 政黨對應候選人）
    rows = conn.execute(
        """SELECT er.candidate_id, SUM(er.votes) AS total_votes
           FROM election_results er
           WHERE er.election_id = ?
           GROUP BY er.candidate_id""",
        (election_id,)
    ).fetchall()

    if not rows:
        print(f"  election_id={election_id}: 無資料，跳過")
        return

    total_all_votes = sum(r["total_votes"] for r in rows)
    threshold_votes = total_all_votes * THRESHOLD

    # 過濾門檻
    qualifying: dict[int, int] = {}
    for r in rows:
        if r["total_votes"] >= threshold_votes:
            qualifying[r["candidate_id"]] = r["total_votes"]

    if not qualifying:
        print(f"  election_id={election_id}: 無政黨通過 5% 門檻")
        return

    seats = allocate_seats(qualifying, total_seats)

    # 顯示分配結果
    party_names = {}
    for cid in qualifying:
        name_row = conn.execute(
            "SELECT c.name FROM candidates c WHERE c.candidate_id = ?", (cid,)
        ).fetchone()
        party_names[cid] = name_row["name"] if name_row else str(cid)

    print(f"\n  election_id={election_id}  date={election_date}  總席次={total_seats}")
    print(f"  {'政黨':<12} {'票數':>12} {'得票率':>8} {'席次':>6}")
    print(f"  {'-'*46}")
    for cid, votes in sorted(qualifying.items(), key=lambda x: -x[1]):
        pct = votes / total_all_votes * 100
        s = seats.get(cid, 0)
        print(f"  {party_names[cid]:<12} {votes:>12,} {pct:>7.2f}% {s:>5}")

    total_allocated = sum(seats.values())
    print(f"  {'合計':<12} {sum(qualifying.values()):>12,} {'':>8} {total_allocated:>5}  (門檻以下票數不計入)")

    if dry_run:
        return

    # 先將本次選舉所有 elected 清零
    conn.execute(
        "UPDATE election_results SET elected = 0 WHERE election_id = ?",
        (election_id,)
    )

    # 有席次的政黨設 elected = 1
    for cid, s in seats.items():
        if s > 0:
            conn.execute(
                "UPDATE election_results SET elected = 1 WHERE election_id = ? AND candidate_id = ?",
                (election_id, cid)
            )

    conn.commit()
    print(f"  → 已更新：{sum(1 for s in seats.values() if s > 0)} 個政黨 elected=1")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只顯示結果，不寫入 DB")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    elections = conn.execute(
        "SELECT election_id, name, date FROM elections WHERE description = '不分區政黨' ORDER BY date"
    ).fetchall()

    if not elections:
        print("資料庫中無不分區政黨選舉，請先執行 import_votedata.py")
        conn.close()
        return

    print(f"找到 {len(elections)} 場不分區政黨選舉")
    for e in elections:
        process_election(conn, e["election_id"], e["date"], args.dry_run)

    conn.close()
    tag = "[dry-run] " if args.dry_run else ""
    print(f"\n{tag}完成")


if __name__ == "__main__":
    main()
