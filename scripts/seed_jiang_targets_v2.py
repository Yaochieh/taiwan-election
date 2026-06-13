"""
蔣萬安 政見追蹤 v2 — parent/child 細分指標 + 多來源。

設計：
  父目標：政見大方向（社宅、長照、都更...）
  子目標：可量化的細分指標（完工/開工/規劃 各自獨立）
  每筆進度可掛多個資料來源，標註 authority_level：
    1 = 政府開放資料/官方公告（最權威）
    2 = 監督單位/議員質詢
    3 = 主流媒體
    4 = 一般媒體/評論
    5 = 部落格/個人

執行：
  python scripts/seed_jiang_targets_v2.py
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"

PERSON = "蔣萬安"
ELECTION_ID = 49


# 父目標
PARENT_TARGETS = [
    {
        "category": "住宅",
        "title": "社會住宅興辦（任內 1.5 萬戶）",
        "description": "蔣萬安 2022 政見：4 年任內推動 1.5 萬戶社宅；長期目標 5 萬戶。"
                       "市府將「興辦」拆成規劃、開工、完工、入住四個階段。",
        "metric_unit": "戶",
        "baseline_value": None,
        "baseline_date": None,
        "target_value": 15000,
        "target_date": "2026-12-24",
        "status": "in_progress",
        "data_source_kind": "mixed",
        "source_url": "https://udn.com/news/story/7323/7969405",
        "rank": 1,
        "children": [
            {
                "title": "已完工戶數",
                "description": "社宅實際完工可入住",
                "metric_unit": "戶",
                "baseline_value": 0,
                "baseline_date": "2022-12-25",
                "target_value": 8000,
                "target_date": "2026-12-24",
                "status": "in_progress",
                "data_source_kind": "official_gov",
                "rank": 1,
                "progress": [
                    {
                        "date": "2025-12-20",
                        "value": 4805,
                        "note": "累計完工 13 處、4,805 戶",
                        "sources": [
                            {
                                "url": "https://annewsmedia.com/2025/12/20/regional-focus/14471/",
                                "source_type": "news",
                                "publisher": "安傳媒",
                                "authority_level": 3,
                            },
                            {
                                "url": "https://www-ws.gov.taipei",
                                "source_type": "gov_announce",
                                "publisher": "台北市都發局",
                                "authority_level": 1,
                            },
                        ],
                    },
                ],
            },
            {
                "title": "已開工戶數",
                "metric_unit": "戶",
                "baseline_value": 0,
                "baseline_date": "2022-12-25",
                "target_value": 5000,
                "target_date": "2026-12-24",
                "status": "in_progress",
                "data_source_kind": "official_gov",
                "rank": 2,
                "progress": [
                    {
                        "date": "2024-05-31",
                        "value": 540,
                        "note": "3 處社宅預算初審過關、共 540 戶最快 2025 動工",
                        "sources": [
                            {
                                "url": "https://news.ltn.com.tw/news/politics/breakingnews/4557547",
                                "source_type": "news",
                                "publisher": "自由時報",
                                "authority_level": 3,
                            },
                        ],
                    },
                    {
                        "date": "2025-12-20",
                        "value": 982,
                        "note": "累計開工 5 處、982 戶",
                        "sources": [
                            {
                                "url": "https://annewsmedia.com/2025/12/20/regional-focus/14471/",
                                "source_type": "news",
                                "publisher": "安傳媒",
                                "authority_level": 3,
                            },
                        ],
                    },
                ],
            },
            {
                "title": "規劃中戶數",
                "metric_unit": "戶",
                "baseline_value": 0,
                "baseline_date": "2022-12-25",
                "target_value": 2000,
                "target_date": "2026-12-24",
                "status": "in_progress",
                "data_source_kind": "official_gov",
                "rank": 3,
                "progress": [
                    {
                        "date": "2025-12-20",
                        "value": 1944,
                        "note": "累計啟動規劃 6 處、1,944 戶",
                        "sources": [
                            {
                                "url": "https://annewsmedia.com/2025/12/20/regional-focus/14471/",
                                "source_type": "news",
                                "publisher": "安傳媒",
                                "authority_level": 3,
                            },
                        ],
                    },
                ],
            },
            {
                "title": "已入住戶數",
                "metric_unit": "戶",
                "baseline_value": 0,
                "baseline_date": "2022-12-25",
                "target_value": 5000,
                "target_date": "2026-12-24",
                "status": "in_progress",
                "data_source_kind": "official_gov",
                "rank": 4,
                "progress": [
                    {
                        "date": "2025-12-20",
                        "value": 4653,
                        "note": "累計入住 12 處、4,653 戶",
                        "sources": [
                            {
                                "url": "https://annewsmedia.com/2025/12/20/regional-focus/14471/",
                                "source_type": "news",
                                "publisher": "安傳媒",
                                "authority_level": 3,
                            },
                        ],
                    },
                ],
            },
        ],
    },

    # 長照床位（單一指標）
    {
        "category": "長照",
        "title": "6 個月內增加 500 張長照床位",
        "description": "蔣萬安 2022 政見：透過聯醫系統 6 個月內增 500 張長照床位。"
                       "實際進度遠落後，且受人力不足影響部分床位閒置。",
        "metric_unit": "張",
        "baseline_value": 0,
        "baseline_date": "2022-12-25",
        "target_value": 500,
        "target_date": "2023-06-25",
        "status": "failed",
        "data_source_kind": "mixed",
        "source_url": "https://udn.com/news/story/6656/6608640",
        "rank": 2,
        "children": [],
        "progress": [
            {
                "date": "2023-04-30",
                "value": 100,
                "note": "競選顧問「聯醫 1 院區增 100 長照床」承諾被質疑跳票",
                "sources": [
                    {
                        "url": "https://www.ettoday.net/news/20230430/2489519.htm",
                        "source_type": "news",
                        "publisher": "ETtoday",
                        "authority_level": 3,
                    },
                ],
            },
            {
                "date": "2023-06-25",
                "value": 232,
                "note": "6 個月期限到，實際 232 床（達標 46%）",
                "sources": [
                    {
                        "url": "https://udn.com/news/story/7323/7101213",
                        "source_type": "news",
                        "publisher": "聯合報",
                        "authority_level": 3,
                    },
                ],
            },
            {
                "date": "2023-12-31",
                "value": 322,
                "note": "年底 322 床",
                "sources": [
                    {
                        "url": "https://udn.com/news/story/7323/7101213",
                        "source_type": "news",
                        "publisher": "聯合報",
                        "authority_level": 3,
                    },
                ],
            },
            {
                "date": "2025-12-15",
                "value": 239,
                "note": "聯醫系統設置 289 床、但因人力不足僅開放 239 床使用",
                "sources": [
                    {
                        "url": "https://news.ltn.com.tw/news/Taipei/breakingnews/5248187",
                        "source_type": "news",
                        "publisher": "自由時報",
                        "authority_level": 3,
                    },
                    {
                        "url": "https://news.ltn.com.tw/news/Taipei/breakingnews/5248197",
                        "source_type": "news",
                        "publisher": "自由時報",
                        "authority_level": 3,
                    },
                ],
            },
        ],
    },

    # 公辦都更
    {
        "category": "都市更新",
        "title": "公辦都更 7599 計畫（年 10 案）",
        "description": "蔣萬安 2022 政見：年 10 案公辦都更；上任後推出「公辦都更 7599 專案」"
                       "降低門檻至 75%。",
        "metric_unit": "案",
        "baseline_value": None,
        "baseline_date": None,
        "target_value": None,
        "target_date": None,
        "status": "in_progress",
        "data_source_kind": "mixed",
        "source_url": "https://udn.com/news/story/7323/7014446",
        "rank": 3,
        "children": [
            {
                "title": "已啟動案件",
                "metric_unit": "案",
                "baseline_value": 0,
                "baseline_date": "2022-12-25",
                "target_value": 40,
                "target_date": "2026-12-24",
                "status": "in_progress",
                "data_source_kind": "official_gov",
                "rank": 1,
                "progress": [
                    {
                        "date": "2023-04-30",
                        "value": 1,
                        "note": "上任第一案：文山區木柵路公辦都更代拆",
                        "sources": [
                            {
                                "url": "https://udn.com/news/story/7323/7048403",
                                "source_type": "news",
                                "publisher": "聯合報",
                                "authority_level": 3,
                            },
                        ],
                    },
                    {
                        "date": "2024-12-31",
                        "value": 5,
                        "note": "公辦都更 2.0 首件簽約、累計 5 案",
                        "sources": [
                            {
                                "url": "https://udn.com/news/story/7323/8067062",
                                "source_type": "news",
                                "publisher": "聯合報",
                                "authority_level": 3,
                            },
                        ],
                    },
                ],
            },
            {
                "title": "降低門檻至 75%（政策變更）",
                "metric_unit": "%",
                "baseline_value": 90,
                "baseline_date": "2022-12-25",
                "target_value": 75,
                "target_date": "2023-03-08",
                "status": "achieved",
                "data_source_kind": "official_gov",
                "rank": 2,
                "progress": [
                    {
                        "date": "2023-03-08",
                        "value": 75,
                        "note": "宣布公辦都更 7599 專案、第一階段同意門檻由 90% 降至 75%",
                        "sources": [
                            {
                                "url": "https://vocus.cc/article/6406b122fd897800010137d4",
                                "source_type": "news",
                                "publisher": "Vocus",
                                "authority_level": 4,
                            },
                        ],
                    },
                ],
            },
        ],
    },

    # 電動車充電格
    {
        "category": "交通",
        "title": "2030 年前完成 2000 格電動車充電格",
        "description": "蔣萬安 2022 政見：交通電動化，2030 年前完成 2000 格電動車充電格。"
                       "（目標日期超出 2026 任期。）",
        "metric_unit": "格",
        "baseline_value": 0,
        "baseline_date": "2022-12-25",
        "target_value": 2000,
        "target_date": "2030-12-31",
        "status": "in_progress",
        "data_source_kind": "news_only",
        "source_url": "https://www.businessweekly.com.tw/focus/blog/3011005",
        "rank": 4,
        "children": [],
        "progress": [],
    },
]


def insert_target(conn, t, parent_id=None):
    cur = conn.execute(
        """
        INSERT INTO platform_targets
            (person_name, election_id, parent_target_id, category, title, description,
             metric_unit, baseline_value, baseline_date,
             target_value, target_date, status, data_source_kind, source_url, rank)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            PERSON, ELECTION_ID, parent_id,
            t.get("category"),
            t["title"],
            t.get("description"),
            t.get("metric_unit"),
            t.get("baseline_value"),
            t.get("baseline_date"),
            t.get("target_value"),
            t.get("target_date"),
            t.get("status", "in_progress"),
            t.get("data_source_kind"),
            t.get("source_url"),
            t.get("rank", 0),
        ),
    )
    target_id = cur.lastrowid

    for p in t.get("progress", []):
        prog_cur = conn.execute(
            """
            INSERT INTO platform_target_progress
                (target_id, recorded_at, current_value, note)
            VALUES (?, ?, ?, ?)
            """,
            (target_id, p["date"], p["value"], p["note"]),
        )
        progress_id = prog_cur.lastrowid
        # 多來源
        for s in p.get("sources", []):
            conn.execute(
                """
                INSERT INTO platform_progress_sources
                    (progress_id, url, source_type, publisher, authority_level)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    progress_id,
                    s["url"], s.get("source_type"), s.get("publisher"),
                    s.get("authority_level"),
                ),
            )

    for child in t.get("children", []):
        insert_target(conn, child, parent_id=target_id)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM platform_targets WHERE person_name = ?", (PERSON,))
    conn.commit()

    for t in PARENT_TARGETS:
        insert_target(conn, t)

    conn.commit()

    # 統計
    rows = conn.execute("""
        SELECT COUNT(*) FILTER (WHERE parent_target_id IS NULL) AS parents,
               COUNT(*) FILTER (WHERE parent_target_id IS NOT NULL) AS children,
               COUNT(*) AS total
        FROM platform_targets WHERE person_name = ?
    """, (PERSON,)).fetchone()
    prog = conn.execute("""
        SELECT COUNT(*) FROM platform_target_progress p
        JOIN platform_targets t ON p.target_id = t.target_id
        WHERE t.person_name = ?
    """, (PERSON,)).fetchone()[0]
    src = conn.execute("""
        SELECT COUNT(*) FROM platform_progress_sources ps
        JOIN platform_target_progress p ON ps.progress_id = p.progress_id
        JOIN platform_targets t ON p.target_id = t.target_id
        WHERE t.person_name = ?
    """, (PERSON,)).fetchone()[0]

    conn.close()
    print(f"✓ 已建立 {rows[2]} 個目標 ({rows[0]} 父 + {rows[1]} 子)")
    print(f"  · {prog} 筆進度資料點")
    print(f"  · {src} 個資料來源")


if __name__ == "__main__":
    main()
