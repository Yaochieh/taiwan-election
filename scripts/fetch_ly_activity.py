"""抓每位立委的問政統計：提案數 + 質詢數（用提案人/質詢委員篩選，避開深分頁）。

存到 data/ly_activity.json。不碰 DB。

用法：python scripts/fetch_ly_activity.py
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "ly_activity.json"
LEG = ROOT / "data" / "ly_legislators.json"
BASE = "https://ly.govapi.tw/v2"


def get_total(endpoint: str, params: dict) -> int:
    qs = urllib.parse.urlencode(params)
    url = f"{BASE}/{endpoint}?{qs}&limit=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TaiwanElection/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        t = d.get("total")
        if isinstance(t, dict):
            return t.get("value", 0)
        return t or 0
    except Exception:
        return -1


def main():
    legs = json.loads(LEG.read_text())
    result = {}
    for term in ("11", "10"):
        names = [l["name"] for l in legs["terms"].get(term, [])]
        print(f"\n第 {term} 屆 {len(names)} 位")
        for i, name in enumerate(names, 1):
            bills = get_total("bills", {"屆": term, "提案人": name})
            time.sleep(0.2)
            inter = get_total("interpellations", {"屆": term, "質詢委員": name})
            time.sleep(0.2)
            result[f"{term}|{name}"] = {"term": int(term), "name": name,
                                        "proposals": bills, "interpellations": inter}
            if i % 20 == 0:
                print(f"  {i}/{len(names)}")
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"\n✓ 已存 {OUT}（{len(result)} 位）")
    # 排行前 5
    top = sorted(result.values(), key=lambda x: -(x["proposals"] if x["proposals"]>0 else 0))[:5]
    print("提案數 top5:", [(t["name"], t["proposals"]) for t in top])


if __name__ == "__main__":
    main()
