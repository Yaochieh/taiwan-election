"""
賴清德 政見追蹤 v2 stub — 主要 2024 競選政見的承諾框架。

設計重點：
  目前只記錄承諾本體與時程，progress points 留白
  待後續從衛福部、經濟部、內政部等開放資料 API 接入

執行：
  python scripts/seed_lai_targets.py
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"

PERSON = "賴清德"
ELECTION_ID = 54  # 2024 第16任總統

TARGETS = [
    {
        "category": "醫療",
        "title": "健康台灣：癌症死亡率 2030 年降低 1/3",
        "description": "賴清德 2024 政見：「健康台灣」計畫；目標 2030 年癌症死亡率較 2018 年（85.0/10萬）降低 1/3，"
                       "至 56.7/10萬以下。設立百億癌症新藥基金（112 年）、推動精準醫療、強化篩檢。",
        "metric_unit": "/10萬人",
        "baseline_value": 85.0,
        "baseline_date": "2018-12-31",
        "target_value": 56.7,
        "target_date": "2030-12-31",
        "status": "in_progress",
        "data_source_kind": "official_api",
        "source_url": "https://www.health.gov.tw/cancer",
    },
    {
        "category": "國防",
        "title": "國防預算占 GDP 3%",
        "description": "賴清德 2024 政見：因應中國威脅，國防預算占 GDP 比例提升到 3% 以上。2024 年實際約 2.45%。",
        "metric_unit": "% of GDP",
        "baseline_value": 2.45,
        "baseline_date": "2024-12-31",
        "target_value": 3.0,
        "target_date": "2028-05-19",
        "status": "in_progress",
        "data_source_kind": "official_doc",
        "source_url": "https://www.mnd.gov.tw",
    },
    {
        "category": "住宅",
        "title": "繼續推動社會住宅與包租代管（任內 +13 萬戶）",
        "description": "賴清德 2024 政見：延續蔡英文社宅計畫，4 年任內新增 13 萬戶社宅資源（直接興建 5 萬 + 包租代管 8 萬）。",
        "metric_unit": "戶",
        "baseline_value": 0,
        "baseline_date": "2024-05-20",
        "target_value": 130000,
        "target_date": "2028-05-19",
        "status": "in_progress",
        "data_source_kind": "official_api",
        "source_url": "https://pip.moi.gov.tw/SocialHousing",
    },
    {
        "category": "能源",
        "title": "2030 年再生能源佔比 30%",
        "description": "賴清德 2024 政見：「次世代電網計畫」推動再生能源；2030 年再生能源佔總發電量達 30%。"
                       "2023 年實際約 9.5%。",
        "metric_unit": "% of total generation",
        "baseline_value": 9.5,
        "baseline_date": "2023-12-31",
        "target_value": 30.0,
        "target_date": "2030-12-31",
        "status": "in_progress",
        "data_source_kind": "official_api",
        "source_url": "https://www.taipower.com.tw",
    },
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 找 candidate_id
    cand = conn.execute(
        "SELECT candidate_id FROM candidates WHERE election_id=? AND name=?",
        (ELECTION_ID, PERSON),
    ).fetchone()
    if not cand:
        print(f"✗ 找不到 {PERSON} in election {ELECTION_ID}")
        return

    # 移除既有 targets（重複執行）
    conn.execute(
        "DELETE FROM platform_targets WHERE person_name=?",
        (PERSON,),
    )
    conn.commit()

    rank = 0
    for t in TARGETS:
        conn.execute(
            """INSERT INTO platform_targets
               (person_name, election_id, category, title, description,
                metric_unit, baseline_value, baseline_date,
                target_value, target_date, status,
                source_url, data_source_kind, rank)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                PERSON,
                ELECTION_ID,
                t["category"],
                t["title"],
                t["description"],
                t["metric_unit"],
                t["baseline_value"],
                t["baseline_date"],
                t["target_value"],
                t["target_date"],
                t["status"],
                t.get("source_url"),
                t.get("data_source_kind"),
                rank,
            ),
        )
        rank += 1

    conn.commit()
    print(f"✓ {PERSON} 寫入 {len(TARGETS)} 個父目標")
    conn.close()


if __name__ == "__main__":
    main()
