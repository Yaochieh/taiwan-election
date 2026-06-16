"""
為每個主題建議「可追蹤的政府公開資料來源」清單。

存放在 topic_data_sources 表，前端可在每個主題頁顯示「想追蹤達標
請查這些 API」清單，未來自動接入後可直接顯示進度。

執行：
  python scripts/seed_topic_data_sources.py
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"


# (topic_name, label, url, notes)
SOURCES = [
    # 住宅
    ("住宅", "內政部住宅查詢專區（社會住宅）", "https://pip.moi.gov.tw/V3/E/SCRE0501.aspx",
     "全國社宅辦理戶數、完工/開工/規劃中"),
    ("住宅", "臺北市社會住宅 BigData API", "https://hms.udd.gov.taipei/api/BigData/project",
     "臺北市社宅各案戶數狀態"),
    ("住宅", "data.gov.tw 都市更新事業案件", "https://data.gov.tw/dataset/129516",
     "全國都更案件年度統計"),

    # 長照
    ("長照", "衛福部長照 2.0 服務量", "https://1966.gov.tw/",
     "全國長照服務涵蓋率、ABC 巷弄站點"),
    ("長照", "臺北市長照 API", "https://data.taipei/api/dataset/d455b149-...",
     "臺北市長照床位、服務量"),

    # 醫療
    ("醫療", "衛福部癌症登記資料", "https://www.cdc.gov.tw/Disease",
     "癌症死亡率、發生率（賴清德承諾 2030 降低 1/3）"),
    ("醫療", "全民健保署統計", "https://www.nhi.gov.tw/Content_List.aspx?n=A28310CE6D2828A5",
     "健保支付、醫療資源分布"),

    # 教育
    ("教育", "教育部統計處", "https://stats.moe.gov.tw/", "全國學生數、學費資料"),

    # 交通
    ("交通", "交通部運輸資料", "https://www.motc.gov.tw/", "捷運/鐵道里程、運量"),

    # 環境能源
    ("環境能源", "經濟部能源署電力統計", "https://www.energy.gov.tw/",
     "再生能源占比（賴清德 2030 達 30%）"),
    ("環境能源", "環境部空氣品質監測", "https://airtw.epa.gov.tw/",
     "PM2.5 數值、改善目標"),
    ("環境能源", "中華民國國家溫室氣體排放清冊", "https://www.tgpf.org.tw/",
     "碳排數據、淨零目標進度"),

    # 國防
    ("國防", "國防部國防白皮書 / 國防報告書", "https://www.mnd.gov.tw/",
     "國防預算占 GDP 比 (賴清德 3% 承諾)"),

    # 勞工就業
    ("勞工就業", "勞動部勞動統計", "https://statdb.mol.gov.tw/",
     "薪資、最低工資、失業率"),

    # 經濟產業
    ("經濟產業", "主計總處 GDP 統計", "https://www.dgbas.gov.tw/",
     "GDP 成長率、產業 GDP 占比"),

    # 治安司法
    ("治安司法", "警政署刑案統計", "https://www.npa.gov.tw/",
     "犯罪率、詐騙案件數"),
    ("治安司法", "司法院統計", "https://www.judicial.gov.tw/",
     "案件量、結案率"),

    # 性別平權
    ("性別平權", "性別平等會統計資料", "https://gec.ey.gov.tw/Page/8995",
     "性別薪資差距、女性參政比例"),

    # 農業食安
    ("農業食安", "農業部農業統計", "https://agrstat.coa.gov.tw/",
     "稻米/水果產量、農藥檢驗"),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS topic_data_sources (
            source_id INTEGER PRIMARY KEY,
            topic_id INTEGER NOT NULL REFERENCES platform_topics(topic_id),
            label TEXT NOT NULL,
            url TEXT NOT NULL,
            notes TEXT,
            rank INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_tds_topic ON topic_data_sources(topic_id);
    """)
    conn.commit()

    # 清除舊資料
    conn.execute("DELETE FROM topic_data_sources")

    # 取得 topic_id mapping
    topic_map = {
        r[1]: r[0]
        for r in conn.execute("SELECT topic_id, name FROM platform_topics")
    }

    inserted = 0
    for rank, (topic, label, url, notes) in enumerate(SOURCES):
        tid = topic_map.get(topic)
        if not tid:
            print(f"  ✗ 找不到主題 '{topic}'")
            continue
        conn.execute(
            "INSERT INTO topic_data_sources (topic_id, label, url, notes, rank) "
            "VALUES (?, ?, ?, ?, ?)",
            (tid, label, url, notes, rank),
        )
        inserted += 1

    conn.commit()
    print(f"✓ 寫入 {inserted} 個資料來源")
    conn.close()


if __name__ == "__main__":
    main()
