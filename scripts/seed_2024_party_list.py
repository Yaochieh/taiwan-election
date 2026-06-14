"""
2024 第 11 屆立委不分區當選人 hardcoded seed（34 人）。

來源：中選會公告（民國 113 年 1 月 13 日選舉）
  https://web.cec.gov.tw/

Hare quota 配額結果：
  - 民進黨 (民主進步黨): 13 席
  - 國民黨 (中國國民黨): 13 席
  - 民眾黨 (台灣民眾黨): 8 席

執行：
  python scripts/seed_2024_party_list.py
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"
ELECTION_ID = 50  # 2024 不分區政黨

WINNERS = {
    "民主進步黨": [
        "蔡其昌", "沈伯洋", "范雲", "鍾佳濱", "林楚茵",
        "王正旭", "林月琴", "陳培瑜", "王義川", "莊瑞雄",
        "吳秉叡", "林淑芬", "郭昱晴",
    ],
    "中國國民黨": [
        "韓國瑜", "柯志恩", "葛如鈞", "翁曉玲", "陳菁徽",
        "吳宗憲", "林倩綺", "陳永康", "許宇甄", "謝龍介",
        "蘇清泉", "張嘉郡", "王育敏",
    ],
    "台灣民眾黨": [
        "黃珊珊", "黃國昌", "陳昭姿", "吳春城", "麥玉珍",
        "林國成", "林憶君", "張啓楷",
    ],
}


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 移除舊的「(政黨 第 N 順位)」placeholder candidates
    conn.execute(
        "DELETE FROM candidates WHERE election_id=? AND name LIKE '(%順位)'",
        (ELECTION_ID,),
    )
    conn.execute(
        "DELETE FROM election_results WHERE election_id=? AND candidate_id NOT IN (SELECT candidate_id FROM candidates)",
        (ELECTION_ID,),
    )
    conn.commit()

    total = 0
    for party, names in WINNERS.items():
        party_row = conn.execute(
            "SELECT party_id FROM parties WHERE name = ?", (party,)
        ).fetchone()
        party_id = party_row["party_id"] if party_row else None
        for rank, name in enumerate(names, start=1):
            ex = conn.execute(
                "SELECT candidate_id FROM candidates WHERE election_id=? AND name=?",
                (ELECTION_ID, name),
            ).fetchone()
            if ex:
                cid = ex["candidate_id"]
                conn.execute(
                    "UPDATE candidates SET party_id=?, background=? WHERE candidate_id=?",
                    (party_id, f"不分區立委（{party} 第 {rank} 順位）", cid),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO candidates (election_id, name, party_id, background, district) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ELECTION_ID, name, party_id, f"不分區立委（{party} 第 {rank} 順位）", "不分區"),
                )
                cid = cur.lastrowid
            # election_results row
            er = conn.execute(
                "SELECT result_id FROM election_results WHERE election_id=? AND candidate_id=?",
                (ELECTION_ID, cid),
            ).fetchone()
            if er:
                conn.execute(
                    "UPDATE election_results SET district=?, votes=?, elected=? WHERE result_id=?",
                    ("不分區", 0, 1, er["result_id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO election_results "
                    "(election_id, candidate_id, district, votes, elected) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ELECTION_ID, cid, "不分區", 0, 1),
                )
            total += 1

    conn.commit()
    print(f"✓ 寫入 {total} 位 2024 不分區當選立委")
    # Verify
    for party in WINNERS:
        c = conn.execute(
            "SELECT COUNT(*) FROM candidates c JOIN parties p ON c.party_id=p.party_id "
            "WHERE c.election_id=? AND p.name=?",
            (ELECTION_ID, party),
        ).fetchone()[0]
        print(f"  {party}: {c} 位")
    conn.close()


if __name__ == "__main__":
    main()
