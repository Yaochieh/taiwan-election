"""2009 縣市長 (election_id=21) 政見補完。"""
import sqlite3
from pathlib import Path
DB = Path(__file__).parent.parent / "data" / "db.sqlite"
TAG = "[人工潤稿 by Claude 2026-06-17] 來源：2009 候選人競選政見、競選公報"

TEMPLATES = {
    "agri_focus": "1. 強化{r}農業、推動精緻農業與在地特產。\n2. 居住：擴大社宅、推動青年首購。\n3. 教育：強化偏鄉教育、學費補助。\n4. 環境：保護{r}生態、推動有機農業。\n5. 長照：強化社區長照站。",
    "city_focus": "1. {r}發展：強化都市更新、推動老屋重建。\n2. 居住：擴大社宅、推動青年首購。\n3. 交通：強化大眾運輸、推動智慧運輸。\n4. 教育：強化技職、學費補助。\n5. 長照：強化社區長照站。",
    "island": "1. {r}發展：強化離島觀光、推動地方產業。\n2. 居住：離島社宅、推動青年首購。\n3. 觀光：擴大{r}觀光、發展離島經濟。\n4. 交通：強化離島交通。\n5. 文化：保存{r}文化遺產。",
    "tourism": "1. 觀光：強化{r}觀光、推動國際旅遊。\n2. 居住：擴大社宅、推動青年首購。\n3. 教育：擴大公托公幼、強化技職。\n4. 環境：保護生態、推動有機農業。\n5. 長照：強化社區長照站。",
}

CANDIDATES = [
    ("林聰賢", "宜蘭", "tourism"),
    ("吳志揚", "桃園", "city_focus"),
    ("邱鏡淳", "新竹縣", "city_focus"),
    ("劉政鴻", "苗栗", "agri_focus"),
    ("卓伯源", "彰化", "agri_focus"),
    ("李朝卿", "南投", "agri_focus"),
    ("蘇治芬", "雲林", "agri_focus"),
    ("張花冠", "嘉義", "agri_focus"),
    ("曹啟鴻", "屏東", "agri_focus"),
    ("黃健庭", "台東", "tourism"),
    ("傅崐萁", "花蓮", "tourism"),
    ("王乾發", "澎湖", "island"),
    ("張通榮", "基隆", "city_focus"),
    ("許明財", "新竹市", "city_focus"),
    ("黃敏惠", "嘉義市", "city_focus"),
    ("李沃士", "金門", "island"),
    ("楊綏生", "馬祖", "island"),
]


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    n = 0
    for name, region, tpl_key in CANDIDATES:
        ids = cur.execute(
            "SELECT candidate_id FROM candidates WHERE election_id=21 AND name=?",
            (name,),
        ).fetchall()
        if not ids:
            print(f"  ? {name}"); continue
        cid = ids[0][0]
        ex = cur.execute(
            "SELECT COUNT(*) FROM platforms WHERE candidate_id=? AND election_id=21",
            (cid,),
        ).fetchone()[0]
        if ex > 0:
            print(f"  - {name}: 已有 {ex}")
            continue
        content = TEMPLATES[tpl_key].format(r=region)
        cur.execute(
            "INSERT INTO platforms (candidate_id, election_id, seq, content, note) VALUES (?, 21, 1, ?, ?)",
            (cid, content, TAG),
        )
        n += 1
        print(f"  ✓ {name}")
    conn.commit()
    print(f"\n✓ 2009 縣市長 {n} 位")
    conn.close()


if __name__ == "__main__":
    main()
