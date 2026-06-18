"""抓內政部戶政 ODRP028(出生數按生母)，加總出全國各年出生數。

存 data/births.json：{民國年: 全國出生數}

用法：python scripts/fetch_births.py
"""
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "births.json"
BASE = "https://www.ris.gov.tw/rs-opendata/api/v1/datastore/ODRP028"

# 民國年 → 西元
YEARS = [101, 103, 105, 107, 109, 111, 112, 113]


def fetch_year_total(yyy: int) -> int | None:
    page = 1
    total = 0
    total_page = None
    got = False
    while True:
        url = f"{BASE}/{yyy}?page={page}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TaiwanElection/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
        except Exception as e:
            print(f"  {yyy} page{page} err: {e}")
            break
        rows = d.get("responseData", [])
        if not rows:
            break
        got = True
        for row in rows:
            try:
                total += int(row.get("birth_count", 0) or 0)
            except ValueError:
                pass
        if total_page is None:
            total_page = int(d.get("totalPage", 1))
        print(f"  民國{yyy} page{page}/{total_page} 累計 {total}", end="\r")
        if page >= total_page:
            break
        page += 1
        time.sleep(0.1)
    print()
    return total if got else None


def main():
    result = {}
    for yyy in YEARS:
        print(f"=== 民國 {yyy} ({yyy+1911}) ===")
        t = fetch_year_total(yyy)
        if t:
            result[str(yyy)] = {"ad": yyy + 1911, "births": t}
            print(f"  → {yyy+1911} 年出生 {t:,}")
        time.sleep(0.3)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"\n✓ 已存 {OUT}")
    for y, v in sorted(result.items()):
        print(f"  {v['ad']}: {v['births']:,}")


if __name__ == "__main__":
    main()
