"""
種蔣萬安 2022 競選的可量化政見目標 + 已知進度。

⚠️ 數字以**公開可查的估算**為主，僅供示範與驗證系統可運作。
   實際正式上線前，所有數字需要重新查證並標註可信來源。
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"

PERSON = "蔣萬安"
ELECTION_ID = 49  # 2022 縣市長選舉

# (政見) 大綱
TARGETS = [
    {
        "category": "住宅",
        "title": "4 年內興建 1.5 萬戶社會住宅",
        "description": "蔣萬安 2022 政見：任期 4 年內，新增完工 1.5 萬戶社會住宅；含已動工、規劃中。",
        "metric_unit": "戶",
        "baseline_value": 7100,    # 柯文哲市府卸任時完工/動工統計（示範）
        "baseline_date": "2022-12-25",
        "target_value": 22100,     # 7100 + 15000
        "target_date": "2026-12-24",
        "status": "in_progress",
        "source_url": "https://www-ws.gov.taipei/Download.ashx",  # placeholder
        "progress": [
            {"date": "2023-12-31", "value": 9300, "note": "上任滿一年", "source": "台北市府新聞稿（示範）"},
            {"date": "2024-12-31", "value": 12500, "note": "上任滿兩年", "source": "台北市都發局年度報告（示範）"},
            {"date": "2025-12-31", "value": 16800, "note": "上任滿三年", "source": "台北市府開放資料（示範）"},
        ],
    },
    {
        "category": "都市更新",
        "title": "4 年內推動 25 案公辦都更",
        "description": "蔣萬安 2022 政見：四年內啟動 25 件公辦都更案（不含已啟動者），加速老舊建物更新。",
        "metric_unit": "案",
        "baseline_value": 0,
        "baseline_date": "2022-12-25",
        "target_value": 25,
        "target_date": "2026-12-24",
        "status": "in_progress",
        "source_url": "https://uro.gov.taipei",
        "progress": [
            {"date": "2023-12-31", "value": 4, "note": "上任滿一年", "source": "都市更新處公告（示範）"},
            {"date": "2024-12-31", "value": 9, "note": "上任滿兩年", "source": "都市更新處年報（示範）"},
            {"date": "2025-12-31", "value": 14, "note": "上任滿三年", "source": "都市更新處公告（示範）"},
        ],
    },
    {
        "category": "幼兒托育",
        "title": "新增 24 處公托中心",
        "description": "蔣萬安 2022 政見：四年內公辦或公私協力新增 24 處公共托嬰/托育中心。",
        "metric_unit": "處",
        "baseline_value": 47,    # 柯卸任時公托家數
        "baseline_date": "2022-12-25",
        "target_value": 71,
        "target_date": "2026-12-24",
        "status": "in_progress",
        "source_url": "https://www.dosw.gov.taipei",
        "progress": [
            {"date": "2023-12-31", "value": 52, "note": "上任滿一年", "source": "社會局公告（示範）"},
            {"date": "2024-12-31", "value": 58, "note": "上任滿兩年", "source": "社會局年度報告（示範）"},
            {"date": "2025-12-31", "value": 64, "note": "上任滿三年", "source": "社會局公告（示範）"},
        ],
    },
    {
        "category": "交通",
        "title": "推動北環段捷運完工",
        "description": "蔣萬安 2022 政見：任期內加速捷運北環段建設並如期完工通車（規劃 2027 通車）。",
        "metric_unit": "%",
        "baseline_value": 65,
        "baseline_date": "2022-12-25",
        "target_value": 100,
        "target_date": "2026-12-24",
        "status": "in_progress",
        "source_url": "https://www-ws.gov.taipei",
        "progress": [
            {"date": "2023-12-31", "value": 73, "note": "工程進度", "source": "捷運局公告（示範）"},
            {"date": "2024-12-31", "value": 82, "note": "工程進度", "source": "捷運局公告（示範）"},
            {"date": "2025-12-31", "value": 90, "note": "工程進度", "source": "捷運局公告（示範）"},
        ],
    },
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    # 先清除既有 demo 資料（避免重複）
    conn.execute(
        "DELETE FROM platform_targets WHERE person_name = ?", (PERSON,)
    )
    conn.commit()

    inserted = 0
    for t in TARGETS:
        progress = t.pop("progress", [])
        cur = conn.execute(
            """
            INSERT INTO platform_targets
                (person_name, election_id, category, title, description,
                 metric_unit, baseline_value, baseline_date,
                 target_value, target_date, status, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                PERSON, ELECTION_ID, t["category"], t["title"], t["description"],
                t["metric_unit"], t["baseline_value"], t["baseline_date"],
                t["target_value"], t["target_date"], t["status"], t["source_url"],
            ),
        )
        target_id = cur.lastrowid

        for p in progress:
            conn.execute(
                """
                INSERT INTO platform_target_progress
                    (target_id, recorded_at, current_value, note, source_url)
                VALUES (?, ?, ?, ?, ?)
                """,
                (target_id, p["date"], p["value"], p["note"], p.get("source")),
            )
        inserted += 1

    conn.commit()
    conn.close()
    print(f"✓ 已建立 {inserted} 個 {PERSON} 的政見追蹤目標")


if __name__ == "__main__":
    main()
