"""2025 大罷免投票結果匯入（idempotent，可重跑）。

資料來源（官方公告）：
- 7/26 24立委+高虹安：https://web.cec.gov.tw/central/article/60805
- 8/23 7立委：https://web.cec.gov.tw/central/article/61262
- 7/13 南投縣議員陳玉鈴：https://web.cec.gov.tw/central/article/60537

數字取自維基百科「大罷免投票列表」各案審定後投票結果表（引中選會公告），
以程式解析原始 wikitext 取得，逐案通過「同意+不同意=有效票」加總驗算，
並與遠見/客新聞/中央社交叉比對；林德福案採選委會更正審定後數字。
7案同意票達門檻名單（王鴻薇、李彥秀、徐巧芯、葉元之、羅廷瑋、傅崐萁、
鄭正鈐）與中央社公告一致。

ROWS 欄位：(election_id, 被罷免人, 職務, 政黨, 選區, 選舉人數, 門檻票數,
            同意票, 不同意票, 有效票, 無效票, 總投票數, 達門檻, 通過, note, source_url)
"""
import sqlite3

DB = "data/db.sqlite"

ROWS = [
    (89, '林沛祥', '立法委員', '中國國民黨', '基隆市選舉區', 303980, 75995, 65143, 96294, 161437, 826, 162263, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '王鴻薇', '立法委員', '中國國民黨', '臺北市第3選舉區', 274312, 68578, 76463, 86311, 162774, 678, 163452, 1, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '李彥秀', '立法委員', '中國國民黨', '臺北市第4選舉區', 311887, 77972, 78560, 105169, 183729, 725, 184454, 1, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '羅智強', '立法委員', '中國國民黨', '臺北市第6選舉區', 228981, 57246, 56726, 74808, 131534, 569, 132103, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '徐巧芯', '立法委員', '中國國民黨', '臺北市第7選舉區', 231139, 57785, 62633, 75401, 138034, 596, 138630, 1, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '賴士葆', '立法委員', '中國國民黨', '臺北市第8選舉區', 244753, 61189, 55958, 86907, 142865, 624, 143489, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '洪孟楷', '立法委員', '中國國民黨', '新北市第1選舉區', 405060, 101265, 94808, 121592, 216400, 1146, 217546, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '葉元之', '立法委員', '中國國民黨', '新北市第7選舉區', 231042, 57761, 63357, 66917, 130274, 687, 130961, 1, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '張智倫', '立法委員', '中國國民黨', '新北市第8選舉區', 288291, 72073, 67131, 95319, 162450, 1030, 163480, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '林德福', '立法委員', '中國國民黨', '新北市第9選舉區', 237380, 59345, 51288, 84058, 135346, 715, 136061, 0, 0, '永和區一投開票所同意/不同意票數誤置，經新北市選委會函報中選會於審定時更正；本表為審定後數字', 'https://web.cec.gov.tw/central/article/60805'),
    (90, '羅明才', '立法委員', '中國國民黨', '新北市第11選舉區', 299652, 74913, 49990, 96691, 146681, 1278, 147959, 0, 0, None, 'https://web.cec.gov.tw/central/article/61262'),
    (89, '廖先翔', '立法委員', '中國國民黨', '新北市第12選舉區', 266243, 66561, 60632, 79110, 139742, 714, 140456, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '牛煦庭', '立法委員', '中國國民黨', '桃園市第1選舉區', 354065, 88517, 86734, 106637, 193371, 988, 194359, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '涂權吉', '立法委員', '中國國民黨', '桃園市第2選舉區', 316423, 79106, 70310, 101419, 171729, 936, 172665, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '魯明哲', '立法委員', '中國國民黨', '桃園市第3選舉區', 309001, 77251, 66301, 105323, 171624, 771, 172395, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '萬美玲', '立法委員', '中國國民黨', '桃園市第4選舉區', 306688, 76672, 72626, 97544, 170170, 825, 170995, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '呂玉玲', '立法委員', '中國國民黨', '桃園市第5選舉區', 282711, 70678, 59756, 98042, 157798, 829, 158627, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '邱若華', '立法委員', '中國國民黨', '桃園市第6選舉區', 285041, 71261, 61635, 92049, 153684, 923, 154607, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '鄭正鈐', '立法委員', '中國國民黨', '新竹市選舉區', 357063, 89266, 89970, 119305, 209275, 1410, 210685, 1, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (90, '林思銘', '立法委員', '中國國民黨', '新竹縣第2選舉區', 238499, 59625, 33813, 76239, 110052, 1283, 111335, 0, 0, None, 'https://web.cec.gov.tw/central/article/61262'),
    (90, '顏寬恒', '立法委員', '中國國民黨', '臺中市第2選舉區', 307742, 76936, 54396, 98809, 153205, 1707, 154912, 0, 0, None, 'https://web.cec.gov.tw/central/article/61262'),
    (90, '楊瓊瓔', '立法委員', '中國國民黨', '臺中市第3選舉區', 260599, 65150, 43677, 83511, 127188, 1375, 128563, 0, 0, None, 'https://web.cec.gov.tw/central/article/61262'),
    (89, '廖偉翔', '立法委員', '中國國民黨', '臺中市第4選舉區', 337718, 84430, 83812, 106534, 190346, 991, 191337, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '黃健豪', '立法委員', '中國國民黨', '臺中市第5選舉區', 374348, 93587, 88914, 119540, 208454, 976, 209430, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '羅廷瑋', '立法委員', '中國國民黨', '臺中市第6選舉區', 277436, 69359, 74012, 86422, 160434, 871, 161305, 1, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (90, '江啟臣', '立法委員', '中國國民黨', '臺中市第8選舉區', 208849, 52213, 33977, 69796, 103773, 1151, 104924, 0, 0, None, 'https://web.cec.gov.tw/central/article/61262'),
    (90, '馬文君', '立法委員', '中國國民黨', '南投縣第1選舉區', 184153, 46039, 29914, 59828, 89742, 944, 90686, 0, 0, None, 'https://web.cec.gov.tw/central/article/61262'),
    (90, '游顥', '立法委員', '中國國民黨', '南投縣第2選舉區', 195068, 48767, 33853, 61443, 95296, 1140, 96436, 0, 0, None, 'https://web.cec.gov.tw/central/article/61262'),
    (89, '丁學忠', '立法委員', '中國國民黨', '雲林縣第1選舉區', 271663, 67916, 57331, 77164, 134495, 975, 135470, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '傅崐萁', '立法委員', '中國國民黨', '花蓮縣選舉區', 191367, 47842, 48969, 65300, 114269, 737, 115006, 1, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '黃建賓', '立法委員', '中國國民黨', '臺東縣選舉區', 113385, 28347, 21105, 34907, 56012, 246, 56258, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (89, '高虹安', '新竹市長', '台灣民眾黨', '新竹市', 360311, 90078, 86291, 124360, 210651, 1374, 212025, 0, 0, None, 'https://web.cec.gov.tw/central/article/60805'),
    (91, '陳玉鈴', '南投縣議員', '中國國民黨', '南投縣第4選舉區（草屯鎮）', 57207, 14302, 12160, 5867, 18027, 144, 18171, 0, 0, None, 'https://web.cec.gov.tw/central/article/60537')
]


def main():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recall_results (
            recall_id      INTEGER PRIMARY KEY,
            election_id    INTEGER NOT NULL REFERENCES elections(election_id),
            target_name    TEXT NOT NULL,
            target_office  TEXT NOT NULL,
            party          TEXT,
            district       TEXT,
            electors       INTEGER,
            threshold_votes INTEGER,
            agree_votes    INTEGER NOT NULL,
            disagree_votes INTEGER NOT NULL,
            valid_votes    INTEGER,
            invalid_votes  INTEGER,
            total_votes    INTEGER,
            threshold_met  INTEGER NOT NULL DEFAULT 0,
            passed         INTEGER NOT NULL DEFAULT 0,
            note           TEXT,
            source_url     TEXT NOT NULL,
            UNIQUE(election_id, target_name)
        )
    """)
    # 陳玉鈴案的選舉列（7/13 南投縣議員罷免）
    conn.execute("""
        INSERT OR IGNORE INTO elections (election_id, name, type, date, status, description)
        VALUES (91, '2025年南投縣議員罷免投票', 'council', '2025-07-13', 'completed',
                '南投縣議會第4選舉區議員陳玉鈴罷免案（同意多於不同意但未達門檻，否決）')
    """)
    n = 0
    for row in ROWS:
        # 加總驗算：同意+不同意=有效
        assert row[7] + row[8] == row[9], f"驗算失敗: {row[1]}"
        cur = conn.execute("""
            INSERT INTO recall_results (election_id, target_name, target_office, party,
                district, electors, threshold_votes, agree_votes, disagree_votes,
                valid_votes, invalid_votes, total_votes, threshold_met, passed, note, source_url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(election_id, target_name) DO UPDATE SET
                agree_votes=excluded.agree_votes, disagree_votes=excluded.disagree_votes,
                valid_votes=excluded.valid_votes, invalid_votes=excluded.invalid_votes,
                total_votes=excluded.total_votes, threshold_met=excluded.threshold_met,
                note=excluded.note, source_url=excluded.source_url
        """, row)
        n += cur.rowcount
    # 更新選舉描述（拿掉「尚未匯入」）
    conn.execute("""UPDATE elections SET description='針對 24 位國民黨立委罷免案 + 新竹市長高虹安罷免案，25案全數否決（7案同意票達門檻但不同意票較多）'
                    WHERE election_id=89""")
    conn.execute("""UPDATE elections SET description='針對 7 位國民黨立委罷免案（新北/新竹縣/台中/南投），全數否決'
                    WHERE election_id=90""")
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM recall_results").fetchone()[0]
    print(f"✓ upsert {n} 筆，recall_results 共 {total} 筆")


if __name__ == "__main__":
    main()
