"""
蔣萬安 2022 競選的可量化政見 + 真實公開資料。

資料來源都是台灣新聞媒體的公開報導（自由時報、聯合報、商周等），
URL 標註在每筆 progress 紀錄中，讓使用者可查證。

⚠️ 數字以新聞報導為主，未必與市府最新統計完全一致；
   未來可加入「市府開放資料 API」自動同步。
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"

PERSON = "蔣萬安"
ELECTION_ID = 49  # 2022 縣市長選舉

TARGETS = [
    # ── 1. 長照床位（已跳票） ──────────────────────────────────────
    {
        "category": "長照",
        "title": "6 個月內增加 500 張長照床位",
        "description": "蔣萬安 2022 競選承諾：透過聯醫系統 6 個月內增加 500 張長照床位。"
                       "上任後實際進度遠落後於承諾，且受人力不足影響部分床位閒置。",
        "metric_unit": "張",
        "baseline_value": 0,
        "baseline_date": "2022-12-25",
        "target_value": 500,
        "target_date": "2023-06-25",
        "status": "failed",
        "source_url": "https://udn.com/news/story/6656/6608640",
        "progress": [
            {
                "date": "2023-04-30",
                "value": 100,
                "note": "「聯醫 1 院區增 100 長照床」承諾被質疑跳票",
                "source": "https://www.ettoday.net/news/20230430/2489519.htm",
            },
            {
                "date": "2023-06-25",
                "value": 232,
                "note": "6 個月期限到，實際 232 床（達標 46%）",
                "source": "https://udn.com/news/story/7323/7101213",
            },
            {
                "date": "2023-12-31",
                "value": 322,
                "note": "年底 322 床，仍未達 500",
                "source": "https://udn.com/news/story/7323/7101213",
            },
            {
                "date": "2025-12-15",
                "value": 239,
                "note": "聯醫系統設置 289 床、但因人力不足僅開放 239 床使用",
                "source": "https://news.ltn.com.tw/news/Taipei/breakingnews/5248187",
            },
        ],
    },

    # ── 2. 社會住宅興建（進行中） ────────────────────────────────
    {
        "category": "住宅",
        "title": "任內推動 1.5 萬戶社會住宅",
        "description": "蔣萬安 2022 政見：4 年任內推動社宅興建 1.5 萬戶（含規劃、開工、完工）。"
                       "長期目標為 5 萬戶（議員質疑該目標若依此速度需 90 年）。",
        "metric_unit": "戶",
        "baseline_value": 0,
        "baseline_date": "2022-12-25",
        "target_value": 15000,
        "target_date": "2026-12-24",
        "status": "in_progress",
        "source_url": "https://udn.com/news/story/7323/7968805",
        "progress": [
            {
                "date": "2023-11-30",
                "value": 300,
                "note": "上任一年僅新增 300 戶（議員苗博雅諷需 90 年達 5 萬戶）",
                "source": "https://news.ltn.com.tw/news/politics/breakingnews/4674608",
            },
            {
                "date": "2024-05-31",
                "value": 540,
                "note": "3 處社宅預算初審過關、共 540 戶最快 2025 動工",
                "source": "https://news.ltn.com.tw/news/politics/breakingnews/4557547",
            },
            {
                "date": "2024-12-31",
                "value": 3500,
                "note": "預計 2025 有 7 處自建社宅完工、總共增 3 千餘戶",
                "source": "https://www.myhousing.com.tw/n/n01/north-taiwan/taipei-city-estate/186863/",
            },
            {
                "date": "2025-12-20",
                "value": 7731,
                "note": "累計已啟動規劃 1,944 戶 + 開工 982 戶 + 完工 4,805 戶",
                "source": "https://annewsmedia.com/2025/12/20/regional-focus/14471/",
            },
        ],
    },

    # ── 3. 公辦都更 7599 計畫（已啟動） ────────────────────────
    {
        "category": "都市更新",
        "title": "推動公辦都更 7599 計畫（年 10 案目標）",
        "description": "蔣萬安 2022 政見：「都更 5 箭」、年 10 案公辦都更；上任後推出"
                       "「公辦都更 7599 專案」、第一階段同意門檻由 90% 降至 75%。",
        "metric_unit": "案",
        "baseline_value": 0,
        "baseline_date": "2022-12-25",
        "target_value": 40,
        "target_date": "2026-12-24",
        "status": "in_progress",
        "source_url": "https://udn.com/news/story/7323/7014446",
        "progress": [
            {
                "date": "2023-03-08",
                "value": 1,
                "note": "宣布公辦都更 7599 專案、降低門檻至 75%",
                "source": "https://vocus.cc/article/6406b122fd897800010137d4",
            },
            {
                "date": "2023-04-30",
                "value": 1,
                "note": "上任第一案：文山區木柵路公辦都更代拆",
                "source": "https://udn.com/news/story/7323/7048403",
            },
            {
                "date": "2024-12-31",
                "value": 5,
                "note": "公辦都更 2.0 首件簽約、拚 2029 完工（推估累計 5 案）",
                "source": "https://udn.com/news/story/7323/8067062",
            },
        ],
    },

    # ── 4. 電動車充電格（跨任期目標） ───────────────────────────
    {
        "category": "交通",
        "title": "2030 年前完成 2000 格電動車充電格",
        "description": "蔣萬安 2022 政見：交通電動化推動，2030 年前於台北市完成 2000 個電動車充電格"
                       "建置（目標日期晚於任期 4 年）。",
        "metric_unit": "格",
        "baseline_value": 0,
        "baseline_date": "2022-12-25",
        "target_value": 2000,
        "target_date": "2030-12-31",
        "status": "in_progress",
        "source_url": "https://www.businessweekly.com.tw/focus/blog/3011005",
        "progress": [],
    },
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM platform_targets WHERE person_name = ?", (PERSON,))
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
                (target_id, p["date"], p["value"], p["note"], p["source"]),
            )
        inserted += 1

    conn.commit()
    conn.close()
    print(f"✓ 已建立 {inserted} 個 {PERSON} 政見追蹤（含真實公開資料來源）")


if __name__ == "__main__":
    main()
