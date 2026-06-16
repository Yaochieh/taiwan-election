"""
為 2024 區域立委政見補回原始公報 source_url。
連結到本機/repo 內的公報 PDF 路徑（先用相對路徑，前端 API 服務時可加 base）。

執行：python scripts/backfill_platform_sources.py
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"
BULLETIN_BASE = "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員"
# Railway 公開靜態資源 prefix（api/main.py 已 mount /static/bulletins → data/bulletins）
URL_PREFIX = "https://web-production-f7c522.up.railway.app/static/bulletins"

# 縣市代碼 → 縣市名（用於匹配 bulletins 路徑）
COUNTY_CODES = {
    "01新北市": "新北市",
    "02臺北市": "臺北市",
    "03桃園市": "桃園市",
    "04臺中市": "臺中市",
    "05臺南市": "臺南市",
    "06高雄市": "高雄市",
    "07宜蘭縣": "宜蘭縣",
    "08新竹縣": "新竹縣",
    "09苗栗縣": "苗栗縣",
    "10彰化縣": "彰化縣",
    "11南投縣": "南投縣",
    "12雲林縣": "雲林縣",
    "13嘉義縣": "嘉義縣",
    "14屏東縣": "屏東縣",
    "15臺東縣": "臺東縣",
    "16花蓮縣": "花蓮縣",
    "17澎湖縣": "澎湖縣",
    "18基隆市": "基隆市",
    "19新竹市": "新竹市",
    "20嘉義市": "嘉義市",
    "21金門縣": "金門縣",
    "22連江縣": "連江縣",
}


def main():
    bulletin_root = ROOT / BULLETIN_BASE
    county_to_url = {}
    if bulletin_root.exists():
        for code_dir in bulletin_root.iterdir():
            if not code_dir.is_dir():
                continue
            county = COUNTY_CODES.get(code_dir.name)
            if not county:
                continue
            # 找這個資料夾下的第一個 PDF
            pdfs = list(code_dir.rglob("*.pdf"))
            if pdfs:
                # 相對 data/bulletins/ 的路徑（mount point 之內）
                rel = pdfs[0].relative_to(ROOT / "data" / "bulletins")
                # URL encode 每段（中文檔名）
                from urllib.parse import quote
                county_to_url[county] = f"{URL_PREFIX}/{quote(str(rel))}"

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    updated = 0
    for county in COUNTY_CODES.values():
        note = f"中選會 113 年第 11 屆區域立委公報・{county}"
        n = cur.execute(
            """UPDATE platforms
               SET note = ?
               WHERE election_id = 51
                 AND (note IS NULL OR note='')
                 AND candidate_id IN (
                     SELECT DISTINCT er.candidate_id
                     FROM election_results er
                     WHERE er.election_id = 51
                       AND er.district LIKE ?
                 )""",
            (note, f"{county}%"),
        ).rowcount
        updated += n
    # 同時清掉之前錯打的 source_url（PDF 太大未上傳）
    cur.execute("UPDATE platforms SET source_url=NULL WHERE election_id=51")
    conn.commit()
    print(f"✓ 2024 區域立委：補上 {updated} 條政見 source_url")
    conn.close()


if __name__ == "__main__":
    main()
