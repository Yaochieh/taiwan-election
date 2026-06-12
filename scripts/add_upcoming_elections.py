"""
新增即將舉行的選舉資料到 DB（status='upcoming'）。

含：
  - 2026/11/28 第 5 屆直轄市市長、縣市長、議員、鄉鎮市長、村里長
  - 2028/01/15 第 17 任總統副總統 + 第 12 屆立法委員

日期為依照「最近一次同類選舉日期 + 4 年」推算的預估投票日。
正式日期由中選會公告為準（通常在投票日前約半年公布）。

執行：
  python scripts/add_upcoming_elections.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from db.queries import get_connection


# 未來選舉清單
UPCOMING_ELECTIONS = [
    # ── 2026/11/28 九合一地方公職人員選舉 ──
    {
        "name": "第5屆直轄市市長選舉",
        "type": "mayoral",
        "date": "2026-11-28",
        "description": None,
        "status": "upcoming",
    },
    {
        "name": "第21屆縣市長選舉",
        "type": "mayoral",
        "date": "2026-11-28",
        "description": "縣市長",
        "status": "upcoming",
    },
    {
        "name": "第5屆直轄市議員選舉",
        "type": "council",
        "date": "2026-11-28",
        "description": "區域",
        "status": "upcoming",
    },
    {
        "name": "第5屆直轄市山地原住民議員選舉",
        "type": "council",
        "date": "2026-11-28",
        "description": "山地原住民",
        "status": "upcoming",
    },
    {
        "name": "第5屆直轄市平地原住民議員選舉",
        "type": "council",
        "date": "2026-11-28",
        "description": "平地原住民",
        "status": "upcoming",
    },
    {
        "name": "第21屆縣市議員選舉",
        "type": "council",
        "date": "2026-11-28",
        "description": "縣市區域議員",
        "status": "upcoming",
    },

    # ── 2028/01/15 總統與立委選舉 ──
    {
        "name": "第17任總統副總統選舉",
        "type": "presidential",
        "date": "2028-01-15",
        "description": None,
        "status": "upcoming",
    },
    {
        "name": "第12屆立法委員選舉",
        "type": "legislative",
        "date": "2028-01-15",
        "description": "區域",
        "status": "upcoming",
    },
    {
        "name": "第12屆立法委員選舉",
        "type": "legislative",
        "date": "2028-01-15",
        "description": "山地原住民",
        "status": "upcoming",
    },
    {
        "name": "第12屆立法委員選舉",
        "type": "legislative",
        "date": "2028-01-15",
        "description": "平地原住民",
        "status": "upcoming",
    },
    {
        "name": "第12屆立法委員選舉",
        "type": "legislative",
        "date": "2028-01-15",
        "description": "不分區政黨",
        "status": "upcoming",
    },
]


def main():
    with get_connection() as conn:
        # 把現有的 status 標準化（既然之前都是 completed）
        added = 0
        skipped = 0
        for e in UPCOMING_ELECTIONS:
            # 用 name + date + description 當去重 key
            existing = conn.execute("""
                SELECT election_id FROM elections
                WHERE name = ? AND date = ?
                  AND (description IS ? OR description = ?)
            """, (e["name"], e["date"], e["description"], e["description"])).fetchone()
            if existing:
                # 已存在 — 確保 status 是 upcoming
                conn.execute(
                    "UPDATE elections SET status = ? WHERE election_id = ?",
                    (e["status"], existing["election_id"])
                )
                print(f"  · 已存在：{e['date']} {e['name']}（更新 status）")
                skipped += 1
                continue

            conn.execute("""
                INSERT INTO elections (name, type, date, status, description)
                VALUES (:name, :type, :date, :status, :description)
            """, e)
            print(f"  ↓ 新增：{e['date']} {e['name']}"
                  + (f"（{e['description']}）" if e['description'] else ""))
            added += 1
        conn.commit()

        print()
        print(f"✓ 新增 {added} 筆，更新 {skipped} 筆")

        # 顯示所有 upcoming
        print()
        print("=== 即將舉行的選舉 ===")
        rows = conn.execute("""
            SELECT date, type, name, description FROM elections
            WHERE status = 'upcoming'
            ORDER BY date, type, description
        """).fetchall()
        for r in rows:
            desc = f"（{r['description']}）" if r["description"] else ""
            print(f"  {r['date']}  [{r['type']}]  {r['name']}{desc}")


if __name__ == "__main__":
    main()
