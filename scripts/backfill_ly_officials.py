"""從立法院 API 補早期屆次立委的官方學經歷（現任首長多為前立委）。

現況：edu_official/career_official 只涵蓋第 10-11 屆；賴清德(≤第8屆)、
蕭美琴/盧秀燕/陳其邁/黃偉哲(≤第9屆)、卓榮泰(≤第4屆) 等人拿不到。
本腳本掃第 4-9 屆，對「還沒有官方學經歷」的人取其最新屆次資料寫入。

冪等：只 UPDATE edu_official IS NULL 的人；來源記在 official_source。

用法：python scripts/backfill_ly_officials.py [--dry-run]
"""
import argparse
import json
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"
BASE = "https://ly.govapi.tw/v2"


def fetch_term(term: int) -> list[dict]:
    qs = urllib.parse.urlencode({"屆": term, "limit": 250})
    req = urllib.request.Request(f"{BASE}/legislators?{qs}",
                                 headers={"User-Agent": "TaiwanElection/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("legislators", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # 已有官方學經歷的人名
    have = {r[0] for r in conn.execute(
        "SELECT DISTINCT name FROM candidates WHERE edu_official IS NOT NULL")}
    # 所有出現在 candidates 的人名（只補站上有的人）
    known = {r[0] for r in conn.execute("SELECT DISTINCT name FROM candidates")}

    best: dict[str, tuple[int, dict]] = {}  # name -> (term, rec) 取最新屆
    for term in range(9, 3, -1):  # 9,8,7,6,5,4
        legs = fetch_term(term)
        print(f"第 {term} 屆 {len(legs)} 位")
        for l in legs:
            name = l.get("委員姓名", "")
            if name in have or name not in known or name in best:
                continue
            edu = l.get("學歷") or []
            car = l.get("經歷") or []
            if not edu and not car:
                continue
            best[name] = (term, l)
        time.sleep(0.4)

    print(f"\n可補 {len(best)} 位")
    n = 0
    for name, (term, l) in sorted(best.items(), key=lambda x: -x[1][0]):
        edu = "\n".join(l.get("學歷") or [])
        car = "\n".join(l.get("經歷") or [])
        src = f"立法院 ly.govapi.tw 第{term}屆立法委員資料"
        if n < 12 or name in ("賴清德", "蕭美琴", "卓榮泰", "盧秀燕", "陳其邁", "黃偉哲"):
            print(f"  {name} (第{term}屆) 學歷{len(l.get('學歷') or [])}條/經歷{len(l.get('經歷') or [])}條")
        if not args.dry_run:
            # 寫到該人最新的 candidate row（profile 查詢用 name 任一列即可）
            conn.execute("""
                UPDATE candidates SET edu_official=?, career_official=?, official_source=?
                WHERE candidate_id = (
                    SELECT c2.candidate_id FROM candidates c2
                    JOIN elections e ON c2.election_id=e.election_id
                    WHERE c2.name=? ORDER BY e.date DESC LIMIT 1)
            """, (edu, car, src, name))
        n += 1
    if not args.dry_run:
        conn.commit()
    print(f"✓ 補上 {n} 位官方學經歷")
    conn.close()


if __name__ == "__main__":
    main()
