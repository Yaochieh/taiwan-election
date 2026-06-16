"""
自動為政見分類主題標籤。

一條政見可有多個主題。用關鍵字配分（出現越多分越高），超過門檻才標。
建議：高分主題 = 主要訴求；低分但有 = 順帶提及。

執行：
  python scripts/tag_platforms_by_topic.py [--dry-run]
"""
import argparse
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"

# 12 大主題 + 關鍵字
TOPICS: dict[str, tuple[str, list[str]]] = {
    "住宅": (
        "🏠",
        ["社宅", "公宅", "社會住宅", "公辦都更", "都更", "包租代管",
         "青年住宅", "青安", "住宅", "租屋", "房屋", "房價", "購屋",
         "房市", "住房", "公共住宅"],
    ),
    "長照": (
        "🧓",
        ["長照", "長期照顧", "失智", "失能", "銀髮", "老人", "樂齡",
         "安養", "照顧服務", "照服員", "日照中心", "長照3.0", "長照2.0"],
    ),
    "醫療": (
        "🏥",
        ["健保", "醫療", "醫院", "醫師", "護理師", "癌症", "疫苗",
         "藥品", "公衛", "心理健康", "精神醫療", "精準醫療", "健康"],
    ),
    "教育": (
        "🎓",
        ["教育", "學校", "校園", "學費", "技職", "雙語", "托育", "幼兒",
         "幼兒園", "學生", "老師", "教師", "課綱", "教改", "高中", "大學",
         "升學", "終身學習"],
    ),
    "交通": (
        "🚆",
        ["捷運", "輕軌", "鐵道", "高鐵", "火車", "公車", "機車", "汽車",
         "停車", "塞車", "道路", "橋梁", "交通", "鐵路", "公路", "客運",
         "鐵公路"],
    ),
    "環境能源": (
        "🌱",
        ["環保", "空汙", "空氣", "PM2.5", "節能", "減碳", "碳排", "再生能源",
         "綠能", "光電", "風電", "核電", "核能", "核四", "廢棄物", "回收",
         "海洋", "河川", "生態", "環評", "永續", "氣候"],
    ),
    "兩岸外交": (
        "🌐",
        ["兩岸", "中國", "中共", "九二共識", "九二", "台獨", "統一",
         "和平", "外交", "邦交", "印太", "美國", "日本", "盟邦",
         "區域組織", "CPTPP", "RCEP", "兩岸關係", "對等"],
    ),
    "國防": (
        "🛡️",
        ["國防", "軍購", "徵兵", "後備", "潛艦", "戰機", "軍人", "國軍",
         "兵役", "軍事", "戰備", "嚇阻", "兵力"],
    ),
    "勞工就業": (
        "👷",
        ["勞工", "勞動", "工會", "薪資", "最低工資", "基本工資", "就業",
         "加班", "過勞", "失業", "勞健保", "退休金", "勞退",
         "外勞", "移工"],
    ),
    "經濟產業": (
        "💼",
        ["經濟", "產業", "半導體", "晶圓", "AI", "人工智慧", "數位", "新創",
         "創業", "稅制", "稅", "金融", "投資", "中小企業", "電動車",
         "科技", "GDP", "產值", "出口"],
    ),
    "治安司法": (
        "⚖️",
        ["治安", "警察", "犯罪", "毒品", "詐騙", "司法", "法官", "檢察",
         "人權", "監所", "再犯", "電信詐騙", "黑金", "暴力"],
    ),
    "性別平權": (
        "🌈",
        ["性別", "女性", "婦女", "同志", "同婚", "LGBTQ", "原住民",
         "新住民", "身障", "身心障礙", "平權", "弱勢", "性平", "性騷",
         "性侵", "凍卵", "代孕"],
    ),
    "農業食安": (
        "🌾",
        ["農業", "農民", "農地", "糧食", "食安", "有機", "漁業", "畜牧",
         "農村", "農會", "農藥", "稻米", "農產品"],
    ),
    "政府改革": (
        "🏛️",
        ["改革", "廉政", "貪腐", "透明", "民主", "憲改", "公開",
         "公民參與", "罷免", "提案", "監督", "預算", "民意"],
    ),
    "文化": (
        "🎨",
        ["文化", "藝術", "母語", "客家", "原民文化", "創意產業",
         "博物館", "藝文", "文資", "古蹟", "文化幣", "電影"],
    ),
}


def ensure_schema(conn: sqlite3.Connection):
    # category 與 junction 表
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS platform_topics (
          topic_id INTEGER PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          icon TEXT,
          rank INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS platform_topic_links (
          platform_id INTEGER NOT NULL REFERENCES platforms(platform_id) ON DELETE CASCADE,
          topic_id INTEGER NOT NULL REFERENCES platform_topics(topic_id) ON DELETE CASCADE,
          score INTEGER NOT NULL,
          PRIMARY KEY (platform_id, topic_id)
        );
        CREATE INDEX IF NOT EXISTS idx_ptl_topic ON platform_topic_links(topic_id);
        CREATE INDEX IF NOT EXISTS idx_ptl_platform ON platform_topic_links(platform_id);
    """)
    # 確保 topics 表都有資料
    for rank, (name, (icon, _)) in enumerate(TOPICS.items()):
        conn.execute(
            "INSERT OR IGNORE INTO platform_topics (name, icon, rank) VALUES (?, ?, ?)",
            (name, icon, rank),
        )
    conn.commit()


def score_text(text: str) -> dict[str, int]:
    """回傳 {topic: score}，score = 該主題關鍵字在文本中出現的次數總和。"""
    scores: dict[str, int] = {}
    for topic, (_, kws) in TOPICS.items():
        s = 0
        for kw in kws:
            s += len(re.findall(re.escape(kw), text))
        if s > 0:
            scores[topic] = s
    return scores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-score", type=int, default=1, help="最低分數（預設 1）")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    # 取得 topic name → id 對應
    topic_map = {
        r["name"]: r["topic_id"]
        for r in conn.execute("SELECT topic_id, name FROM platform_topics").fetchall()
    }

    rows = conn.execute(
        "SELECT platform_id, content FROM platforms"
    ).fetchall()
    print(f"📋 {len(rows)} 條政見要標註")

    # 清除舊資料
    if not args.dry_run:
        conn.execute("DELETE FROM platform_topic_links")

    total_links = 0
    no_topic = 0
    for r in rows:
        scores = score_text(r["content"] or "")
        scores = {t: s for t, s in scores.items() if s >= args.min_score}
        if not scores:
            no_topic += 1
            continue
        for topic, s in scores.items():
            if args.dry_run:
                continue
            conn.execute(
                "INSERT INTO platform_topic_links (platform_id, topic_id, score) "
                "VALUES (?, ?, ?)",
                (r["platform_id"], topic_map[topic], s),
            )
            total_links += 1

    if not args.dry_run:
        conn.commit()
    print(f"✓ 標註 {total_links} 個 (政見, 主題) 連結；{no_topic} 條無主題")

    # 每主題統計
    if not args.dry_run:
        stats = conn.execute("""
            SELECT t.name, t.icon, COUNT(*) AS n
            FROM platform_topic_links l
            JOIN platform_topics t ON l.topic_id = t.topic_id
            GROUP BY t.topic_id ORDER BY n DESC
        """).fetchall()
        print("\n各主題覆蓋：")
        for s in stats:
            print(f"  {s['icon']} {s['name']}: {s['n']} 條政見")
    conn.close()


if __name__ == "__main__":
    main()
