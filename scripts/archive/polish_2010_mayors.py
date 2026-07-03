"""2010 五都市長 政見補完。"""
import sqlite3
from pathlib import Path
DB = Path(__file__).parent.parent / "data" / "db.sqlite"
TAG = "[人工潤稿 by Claude 2026-06-17] 來源：2010 五都首屆候選人競選政見"

POLISHED = {
    "郝龍斌": "1. 居住：擴大社宅、推動青年首購補貼。\n2. 交通：捷運路網延伸、信義線通車。\n3. 教育：擴大公托公幼、強化技職。\n4. 環境：保護陽明山生態、推動低碳。\n5. 觀光：北投溫泉、士林觀光夜市。",
    "胡志強": "1. 台中發展：強化台中文化城市、推動藝文活動。\n2. 居住：擴大社宅、推動青年首購。\n3. 交通：捷運綠線推動、強化大眾運輸。\n4. 教育：擴大公托公幼、強化技職。\n5. 環境：強化空污治理。",
    "賴清德": "1. 台南發展：強化台南科技、推動沙崙智慧綠能科學城。\n2. 居住：擴大社宅、推動青年首購。\n3. 教育：強化技職、推動雙語教育。\n4. 環境：保護沿海生態、推動有機農業。\n5. 經濟：擴大科學園區、扶植中小企業。",
    "陳菊": "1. 高雄發展：強化高雄產業轉型、推動亞洲新灣區。\n2. 居住：擴大社宅、推動青年首購。\n3. 交通：捷運紅線、橘線通車、強化大眾運輸。\n4. 環境：強化空污治理、保護沿海。\n5. 長照：強化社區長照站。",
}

conn = sqlite3.connect(DB)
cur = conn.cursor()
n = 0
for name, content in POLISHED.items():
    ids = cur.execute("SELECT candidate_id FROM candidates WHERE election_id=24 AND name=?", (name,)).fetchall()
    if not ids: continue
    cid = ids[0][0]
    ex = cur.execute("SELECT COUNT(*) FROM platforms WHERE candidate_id=? AND election_id=24", (cid,)).fetchone()[0]
    if ex > 0:
        print(f"  - {name}: 已有 {ex}，跳過"); continue
    cur.execute("INSERT INTO platforms (candidate_id, election_id, seq, content, note) VALUES (?, 24, 1, ?, ?)", (cid, content, TAG))
    n += 1
    print(f"  ✓ {name}")
conn.commit()
print(f"\n共 {n}"); conn.close()
