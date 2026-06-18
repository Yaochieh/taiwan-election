"""抓立法院記名表決(votes)，計算每位立委的表決參與數 + 贊成/反對。

存 data/ly_votes.json:
  - per_legislator: {term|name: {votes, agree, against, abstain}}
  - notable: 近期重要表決清單(議題+結果)

用法：python scripts/fetch_ly_votes.py
"""
import json
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "ly_votes.json"
BASE = "https://ly.govapi.tw/v2"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "TaiwanElection/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    per = defaultdict(lambda: {"votes": 0, "agree": 0, "against": 0, "abstain": 0})
    notable = []
    for term in (11, 10):
        page = 1
        total_page = None
        while True:
            url = f"{BASE}/votes?%E5%B1%86={term}&limit=100&page={page}"
            try:
                d = get(url)
            except Exception as e:
                print(f"  屆{term} page{page} err: {e}")
                break
            votes = d.get("votes", [])
            if not votes:
                break
            for v in votes:
                agree = v.get("贊成") or []
                against = v.get("反對") or []
                abstain = v.get("棄權") or []
                for n in agree:
                    per[f"{term}|{n}"]["votes"] += 1
                    per[f"{term}|{n}"]["agree"] += 1
                for n in against:
                    per[f"{term}|{n}"]["votes"] += 1
                    per[f"{term}|{n}"]["against"] += 1
                for n in abstain:
                    per[f"{term}|{n}"]["votes"] += 1
                    per[f"{term}|{n}"]["abstain"] += 1
                if term == 11 and len(notable) < 30:
                    res = v.get("表決結果") or {}
                    notable.append({
                        "issue": (v.get("表決議題") or "")[:120],
                        "time": v.get("表決時間"),
                        "agree": res.get("贊成人數"),
                        "against": res.get("反對人數"),
                        "abstain": res.get("棄權人數"),
                    })
            if total_page is None:
                total_page = d.get("total_page", 1)
            print(f"  屆{term} page{page}/{total_page}: {len(per)} 人")
            if page >= total_page:
                break
            page += 1
            time.sleep(0.2)
    result = {"per_legislator": dict(per), "notable": notable}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"\n✓ 已存 {OUT}（{len(per)} 人）")
    top = sorted(per.items(), key=lambda x: -x[1]["votes"])[:5]
    print("表決參與 top5:", [(k.split('|')[1], v["votes"]) for k, v in top])


if __name__ == "__main__":
    main()
