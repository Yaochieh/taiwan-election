"""抓第 11 屆每位立委的提案清單（議案名稱/狀態/URL），供政見×提案對照。

存到 data/ly_bills.json。不碰 DB。來源：ly.govapi.tw v2（立法院開放資料）。

用法：python scripts/fetch_ly_bills.py
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "ly_bills.json"
LEG = ROOT / "data" / "ly_legislators.json"
BASE = "https://ly.govapi.tw/v2"
TERM = "11"


def fetch_page(name: str, page: int) -> dict:
    qs = urllib.parse.urlencode({"屆": TERM, "提案人": name, "limit": 100, "page": page})
    req = urllib.request.Request(f"{BASE}/bills?{qs}",
                                 headers={"User-Agent": "TaiwanElection/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    legs = json.loads(LEG.read_text())
    names = [l["name"] for l in legs["terms"][TERM]]
    print(f"第 {TERM} 屆 {len(names)} 位立委")

    # 續跑：已抓過的跳過
    result = json.loads(OUT.read_text()) if OUT.exists() else {}

    for i, name in enumerate(names, 1):
        if name in result:
            continue
        bills = []
        page = 1
        while True:
            try:
                d = fetch_page(name, page)
            except Exception as e:
                print(f"  ✗ {name} p{page}: {e}")
                time.sleep(2)
                break
            for b in d.get("bills", []):
                bills.append({
                    "title": b.get("議案名稱", ""),
                    "status": b.get("議案狀態", ""),
                    "no": b.get("議案編號", ""),
                    "url": b.get("url", ""),
                    "date": b.get("最新進度日期", ""),
                })
            total = d.get("total", 0)
            if isinstance(total, dict):
                total = total.get("value", 0)
            if page * 100 >= total or not d.get("bills"):
                break
            page += 1
            time.sleep(0.25)
        result[name] = bills
        # 每位存檔一次，中斷不損失
        OUT.write_text(json.dumps(result, ensure_ascii=False))
        print(f"  {i}/{len(names)} {name}: {len(bills)} 案")
        time.sleep(0.25)

    print(f"\n✓ 已存 {OUT}（{len(result)} 位）")


if __name__ == "__main__":
    main()
