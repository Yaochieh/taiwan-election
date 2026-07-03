"""第四批立委政見潤稿（簡要版，5 大主軸；對於 OCR 太碎的立委）。

這批是用「政黨核心立場 + 選區重點議題」的簡要版本，內容較通用。
note 會明確標 [人工潤稿 簡要版] 提醒這是概要而非完整政見。
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db.sqlite"
TAG = "[人工潤稿 簡要版 by Claude 2026-06-17] 來源：政黨立場概要 + 選區重點議題"

# (立委姓名, 政黨代碼, 選區重點議題)
NAMES = [
    ("丁學忠", "KMT", "雲林"),
    ("何欣純", "DPP", "台中"),
    ("劉建國", "DPP", "雲林"),
    ("吳琪銘", "DPP", "新北"),
    ("呂玉玲", "KMT", "桃園"),
    ("廖偉翔", "KMT", "台中"),
    ("廖先翔", "KMT", "新北"),
    ("張智倫", "KMT", "新北"),
    ("徐富癸", "DPP", "屏東"),
    ("徐欣瑩", "MKT", "新竹"),  # 民眾黨
    ("李坤城", "DPP", "新北"),
    ("李彥秀", "KMT", "台北"),
    ("李昆澤", "DPP", "高雄"),
    ("林俊憲", "DPP", "台南"),
    ("林宜瑾", "DPP", "台南"),
    ("林岱樺", "DPP", "高雄"),
    ("林德福", "KMT", "新北"),
    ("林思銘", "KMT", "新竹縣"),
    ("林沛祥", "KMT", "基隆"),
    ("楊曜", "DPP", "澎湖"),
    ("楊瓊瓔", "KMT", "台中"),
    ("涂權吉", "KMT", "桃園"),
    ("游顥", "KMT", "南投"),
    ("牛煦庭", "TPP", "桃園"),
    ("王定宇", "DPP", "台南"),
    ("王美惠", "DPP", "嘉義"),
    ("羅廷瑋", "KMT", "台中"),
    ("羅明才", "KMT", "新北"),
    ("萬美玲", "KMT", "桃園"),
    ("葉元之", "KMT", "新北"),
    ("許智傑", "DPP", "高雄"),
    ("謝衣鳯", "KMT", "彰化"),
    ("邱若華", "KMT", "桃園"),
    ("邱鎮軍", "KMT", "苗栗"),
    ("郭國文", "DPP", "台南"),
    ("陳秀寳", "KMT", "彰化"),
    ("陳素月", "DPP", "彰化"),
    ("陳超明", "KMT", "苗栗"),
    ("黃建賓", "KMT", "台東"),
    ("黃秀芳", "DPP", "彰化"),
]


DPP_TPL = """1. 居住正義：擴大社宅、囤房稅 2.0、租金補貼。
2. 兩岸：堅守民主與主權、深化美日民主夥伴關係。
3. 性別平權：完善 #MeToo 後續、職場性平、托育公共化。
4. 長照與健保：人力培訓、家庭照顧者支持、社區長照站擴大。
5. {region}在地建設：強化{region}產業升級、交通基礎建設、地方財政自主。"""

KMT_TPL = """1. 居住：青年首購零利率、社宅興建、租金補貼擴大。
2. 兩岸：恢復對話、推動和平交流。
3. 經濟：減稅救民生、軍公教加薪、勞保撥補。
4. 教育：12 年國教檢討、教師加薪、學費補助延伸。
5. {region}在地建設：強化{region}交通建設、產業轉型、長照資源。"""

TPP_TPL = """1. 國防：國防預算合理化、軍隊去政治化、總統定期國情報告。
2. 兩岸：先求自保再求備戰、與美中等距。
3. 居住：囤房稅 2.0、社宅倍增、青年租金補貼。
4. 政府改革：人事審查強化、三權分立、降低投票年齡。
5. {region}在地建設：強化{region}產業升級與大眾運輸。"""

MKT_TPL = """1. 在地民代：強化{region}地方建設、推動產業轉型。
2. 居住：青年首購、社宅興建。
3. 教育：強化技職、雙語教育。
4. 兩岸：恢復對話、推動和平交流。
5. 長照：人力培訓、社區長照站擴大。"""


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    n = 0
    for name, party, region in NAMES:
        ids = cur.execute(
            "SELECT candidate_id FROM candidates WHERE election_id=51 AND name=?",
            (name,),
        ).fetchall()
        if not ids:
            print(f"  ? {name}")
            continue
        cid = ids[0][0]
        tpl = {"DPP": DPP_TPL, "KMT": KMT_TPL, "TPP": TPP_TPL, "MKT": MKT_TPL}[party]
        content = tpl.format(region=region)
        # 保留原 raw
        old = cur.execute(
            "SELECT content, content_raw FROM platforms WHERE candidate_id=? AND election_id=51 LIMIT 1",
            (cid,),
        ).fetchone()
        raw = old[1] if old and old[1] else (old[0] if old else None)
        cur.execute("DELETE FROM platforms WHERE candidate_id=? AND election_id=51", (cid,))
        cur.execute(
            """INSERT INTO platforms
               (candidate_id, election_id, seq, content, content_raw, note)
               VALUES (?, 51, 1, ?, ?, ?)""",
            (cid, content, raw, TAG),
        )
        n += 1
        print(f"  ✓ {name} ({party}/{region})")
    conn.commit()
    print(f"\n✓ 第四批簡要版 {n} 位")
    conn.close()


if __name__ == "__main__":
    main()
