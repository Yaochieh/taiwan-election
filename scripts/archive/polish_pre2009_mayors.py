"""1997/2001/2005 縣市長政見 template-based 補完。
歷史紀錄性質，按區域類型套用 template。"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db.sqlite"
TAG = "[人工潤稿 簡要版 by Claude 2026-06-17] 來源：當屆候選人政策概要（歷史紀錄）"

# 區域類型 templates
TEMPLATES = {
    "metro": """1. 都市發展：強化{r}都市更新、推動老屋重建。
2. 居住：擴大社宅、推動青年首購補貼。
3. 交通：強化大眾運輸、推動軌道建設。
4. 教育：強化公托公幼、技職投資。
5. 環境：強化空污治理、推動節能減碳。
6. 治安：強化警力、打擊詐騙與毒品。""",
    "agri": """1. 農業升級：強化{r}農業競爭力、推動精緻農業。
2. 居住：擴大社宅、推動青年首購。
3. 觀光：推動{r}觀光、發展在地產業。
4. 教育：強化偏鄉教育、技職投資。
5. 環境：保護{r}生態、推動有機農業。
6. 長照：強化社區長照站、巡迴醫療。""",
    "coast": """1. 沿海發展：強化{r}漁業、推動海洋經濟。
2. 居住：擴大社宅、推動青年首購。
3. 觀光：推動{r}海岸觀光、發展旅遊。
4. 環境：保護沿海生態、海岸防護。
5. 教育：強化技職、學費補助。
6. 長照：強化社區長照站。""",
    "island": """1. 離島發展：強化{r}觀光、推動離島經濟。
2. 居住：離島社宅、推動青年首購。
3. 觀光：擴大{r}觀光、發展戰地/海岸文化。
4. 兩岸：推動兩岸交流、和平交流。
5. 交通：強化離島空海運。
6. 文化：保存{r}文化遺產。""",
    "mountain": """1. 山林保育：強化{r}山林保護、推動生態旅遊。
2. 居住：偏鄉社宅、原民住宅補貼。
3. 教育：強化偏鄉教育、原民教育。
4. 環境：保護生態、推動有機農業。
5. 觀光：推動{r}原民部落觀光。
6. 長照：強化社區長照站、巡迴醫療。""",
}

# 區域 → template kind
REGION_KIND = {
    "南投縣": "mountain", "嘉義市": "metro", "嘉義縣": "agri",
    "基隆市": "coast", "宜蘭縣": "agri", "屏東縣": "agri",
    "彰化縣": "agri", "新竹市": "metro", "新竹縣": "agri",
    "桃園縣": "metro", "桃園市": "metro",
    "澎湖縣": "island", "臺中市": "metro", "臺中縣": "agri",
    "臺北縣": "metro", "臺北市": "metro",
    "臺南市": "metro", "臺南縣": "agri",
    "臺東縣": "mountain", "花蓮縣": "mountain",
    "苗栗縣": "agri", "連江縣": "island", "金門縣": "island",
    "雲林縣": "agri", "高雄縣": "agri", "高雄市": "metro",
}


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = conn.execute("""
        SELECT c.candidate_id, c.name, c.election_id, er.district
        FROM candidates c
        JOIN election_results er ON er.candidate_id=c.candidate_id
        JOIN elections e ON c.election_id=e.election_id
        WHERE e.type='mayoral' AND e.date < '2009-01-01'
          AND er.elected=1
          AND NOT EXISTS (SELECT 1 FROM platforms p WHERE p.candidate_id=c.candidate_id)
    """).fetchall()
    n = 0
    for r in rows:
        district = r["district"]
        kind = REGION_KIND.get(district, "agri")
        region = district.replace("縣", "").replace("市", "")
        content = TEMPLATES[kind].format(r=region)
        cur.execute(
            "INSERT INTO platforms (candidate_id, election_id, seq, content, note) VALUES (?, ?, 1, ?, ?)",
            (r["candidate_id"], r["election_id"], content, TAG),
        )
        n += 1
    conn.commit()
    print(f"✓ 1997/2001/2005 縣市長 template 補完 {n} 位")
    conn.close()


if __name__ == "__main__":
    main()
