"""
將總統選舉候選人的正副連名（如「賴清德/蔡英文」）拆分成兩筆獨立候選人記錄。
- 原 row 改為正總統（background='正總統'）
- 新插入副總統（background='副總統'，同政黨、同 election_id）
- election_results 也各複製一筆（同 votes、elected、district）
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "db.sqlite"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    # 找出所有正副連名候選人
    rows = conn.execute("""
        SELECT c.candidate_id, c.name, c.party_id, c.election_id, c.district
        FROM candidates c
        JOIN elections e ON c.election_id = e.election_id
        WHERE e.type = 'presidential' AND c.name LIKE '%/%'
    """).fetchall()

    print(f"找到 {len(rows)} 筆正副連名記錄")

    for row in rows:
        cid = row["candidate_id"]
        full_name = row["name"]
        parts = full_name.split("/", 1)
        if len(parts) != 2:
            print(f"  跳過（無法拆分）：{full_name}")
            continue

        zheng_name, fu_name = parts[0].strip(), parts[1].strip()
        election_id = row["election_id"]
        party_id = row["party_id"]

        print(f"  拆分：{full_name} → 正:{zheng_name} 副:{fu_name}")

        # 1. 更新正總統：改名、標記 background
        conn.execute("""
            UPDATE candidates SET name=?, background='正總統' WHERE candidate_id=?
        """, (zheng_name, cid))

        # 2. 插入副總統 candidate（若已存在則跳過）
        existing = conn.execute("""
            SELECT candidate_id FROM candidates
            WHERE name=? AND election_id=?
        """, (fu_name, election_id)).fetchone()

        if existing:
            fu_cid = existing["candidate_id"]
            print(f"    副總統 {fu_name} 已存在 (id={fu_cid})，更新 background")
            conn.execute("UPDATE candidates SET background='副總統' WHERE candidate_id=?", (fu_cid,))
        else:
            conn.execute("""
                INSERT INTO candidates (name, party_id, election_id, district, background)
                VALUES (?, ?, ?, ?, '副總統')
            """, (fu_name, party_id, election_id, row["district"]))
            fu_cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            print(f"    副總統 {fu_name} 新增 (id={fu_cid})")

        # 3. 複製 election_results 給副總統
        results = conn.execute("""
            SELECT district, votes, elected FROM election_results
            WHERE candidate_id=? AND election_id=?
        """, (cid, election_id)).fetchall()

        for r in results:
            existing_result = conn.execute("""
                SELECT result_id FROM election_results
                WHERE candidate_id=? AND election_id=? AND district IS ?
            """, (fu_cid, election_id, r["district"])).fetchone()
            if not existing_result:
                conn.execute("""
                    INSERT INTO election_results (election_id, candidate_id, district, votes, elected)
                    VALUES (?, ?, ?, ?, ?)
                """, (election_id, fu_cid, r["district"], r["votes"], r["elected"]))

    conn.commit()
    conn.close()
    print("完成")


if __name__ == "__main__":
    main()
