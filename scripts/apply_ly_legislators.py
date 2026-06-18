"""把 ly_legislators.json 的乾淨學歷/經歷/委員會寫入 candidates。

新增欄位 edu_official / career_official / committees_official / official_source。
只更新「立法委員」選舉的候選人（依姓名+屆對應）。

用法：python scripts/apply_ly_legislators.py
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"
JSON = ROOT / "data" / "ly_legislators.json"

# 屆 → 立委選舉年(西元)
TERM_YEAR = {11: "2024", 10: "2020", 9: "2016"}


def main():
    data = json.loads(JSON.read_text())
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    cur = conn.cursor()
    # 加欄位（容錯）
    for col in ["edu_official TEXT", "career_official TEXT",
                "committees_official TEXT", "official_source TEXT"]:
        try:
            cur.execute(f"ALTER TABLE candidates ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass

    updated = 0
    for term, legs in data["terms"].items():
        year = TERM_YEAR.get(int(term))
        if not year:
            continue
        for l in legs:
            edu = "\n".join(x.strip() for x in l.get("edu", []) if x.strip())
            career = "\n".join(x.strip() for x in l.get("exp", []) if x.strip())
            committees = "\n".join(l.get("committees", []))
            # 對應該屆立委選舉的候選人（姓名 + 選舉年）
            rows = cur.execute(
                """SELECT c.candidate_id FROM candidates c
                   JOIN elections e ON c.election_id=e.election_id
                   WHERE c.name=? AND e.type='legislative'
                     AND strftime('%Y', e.date)=?""",
                (l["name"], year),
            ).fetchall()
            for (cid,) in rows:
                cur.execute(
                    """UPDATE candidates
                       SET edu_official=?, career_official=?, committees_official=?,
                           official_source=?
                       WHERE candidate_id=?""",
                    (edu, career, committees,
                     "立法院開放資料 ly.govapi.tw", cid),
                )
                updated += 1
    conn.commit()
    print(f"✓ 更新 {updated} 位立委候選人的官方學經歷")
    conn.close()


if __name__ == "__main__":
    main()
