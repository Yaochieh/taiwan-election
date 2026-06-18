"""抓立法院開放資料(ly.govapi.tw)的立委資料，存成 JSON。

- 第 10、11 屆立委的乾淨學歷/經歷/照片
- 每位提案數(議案統計)

不碰 DB。輸出到 data/ly_legislators.json，之後由 apply 腳本寫入。

用法：python scripts/fetch_ly_legislators.py
"""
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "ly_legislators.json"
BASE = "https://ly.govapi.tw/v2"


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "TaiwanElection/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_legislators(term: int) -> list[dict]:
    out = []
    page = 1
    while True:
        url = f"{BASE}/legislators?%E5%B1%86={term}&limit=100&page={page}"
        data = get(url)
        legs = data.get("legislators", [])
        if not legs:
            break
        for l in legs:
            out.append({
                "term": l.get("屆"),
                "name": l.get("委員姓名"),
                "party": l.get("黨籍"),
                "area": l.get("選區名稱"),
                "edu": l.get("學歷") or [],
                "exp": l.get("經歷") or [],
                "photo": l.get("照片位址"),
                "committees": l.get("委員會") or [],
                "left": l.get("是否離職"),
                "left_reason": l.get("離職原因"),
            })
        print(f"  屆{term} page{page}: 累計 {len(out)}")
        if page >= data.get("total_page", 1):
            break
        page += 1
        time.sleep(0.3)
    return out


def fetch_proposal_counts(term: int) -> dict[str, int]:
    """統計每位委員的提案數（議案類別=委員提案，數提案人）。"""
    counts: dict[str, int] = {}
    page = 1
    total_page = None
    while True:
        url = f"{BASE}/bills?%E5%B1%86={term}&limit=200&page={page}"
        try:
            data = get(url)
        except Exception as e:
            print(f"  bills page{page} err: {e}")
            break
        bills = data.get("bills", [])
        if not bills:
            break
        for b in bills:
            proposers = b.get("提案人") or ""
            if isinstance(proposers, list):
                names = proposers
            else:
                names = [x.strip() for x in str(proposers).replace("、", " ").split() if x.strip()]
            for n in names:
                counts[n] = counts.get(n, 0) + 1
        if total_page is None:
            total_page = data.get("total_page", 1)
        print(f"  bills 屆{term} page{page}/{total_page}: {len(counts)} 人", end="\r")
        if page >= total_page:
            break
        page += 1
        time.sleep(0.15)
    print()
    return counts


def main():
    result = {"terms": {}}
    for term in (11, 10):
        print(f"\n=== 第 {term} 屆立委 ===")
        legs = fetch_legislators(term)
        print(f"  抓提案數…")
        counts = fetch_proposal_counts(term)
        for l in legs:
            l["proposals"] = counts.get(l["name"], 0)
        result["terms"][str(term)] = legs
        print(f"  屆{term}: {len(legs)} 位立委")
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"\n✓ 已存 {OUT}")


if __name__ == "__main__":
    main()
