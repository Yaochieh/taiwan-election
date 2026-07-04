"""從 targets 的 description/title 推算 target_date（R1，roadmap_2026H2.md）。

規則（保守，抓不到就不填；只填 target_date IS NULL 的列，冪等可重跑）：
  - 「N年內 / N 年內」        → 選舉日 + N 年
  - 「任內」                  → 選舉日 + 4 年（總統/縣市長/立委任期皆 4 年）
  - 「2030 / 2050」等西元年    → 該年 12-31
  - 「民國 NNN 年」            → 西元年 12-31

用法：python scripts/backfill_target_dates.py [--dry-run]
"""
import argparse
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"

RE_N_YEARS = re.compile(r"([一二三四五六七八九十\d]+)\s*年內")
RE_AD_YEAR = re.compile(r"(20[2-9]\d)\s*年")
RE_ROC_YEAR = re.compile(r"民國\s*(1[0-9]\d)\s*年")
RE_TERM = re.compile(r"任內")

CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def parse_n(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    return CN.get(s)


def infer_target_date(text: str, election_date: str | None) -> tuple[str, str] | None:
    """回傳 (target_date, 規則說明) 或 None。"""
    if m := RE_AD_YEAR.search(text):
        return f"{m.group(1)}-12-31", f"西元{m.group(1)}年"
    if m := RE_ROC_YEAR.search(text):
        y = int(m.group(1)) + 1911
        return f"{y}-12-31", f"民國{m.group(1)}年"
    if election_date:
        ey = int(election_date[:4])
        if m := RE_N_YEARS.search(text):
            n = parse_n(m.group(1))
            if n and 1 <= n <= 12:
                return f"{ey + n}-12-31", f"{n}年內(選舉{ey})"
        if RE_TERM.search(text):
            return f"{ey + 4}-12-31", f"任內(選舉{ey}+4)"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT t.target_id, t.title, t.description, e.date AS election_date
        FROM platform_targets t
        LEFT JOIN elections e ON t.election_id = e.election_id
        WHERE t.target_date IS NULL
    """).fetchall()
    print(f"📋 {len(rows)} 筆 target_date 為空")

    filled = 0
    by_rule: dict[str, int] = {}
    for r in rows:
        text = f"{r['title'] or ''}\n{r['description'] or ''}"
        got = infer_target_date(text, r["election_date"])
        if not got:
            continue
        d, rule = got
        rule_key = rule.split("(")[0]
        by_rule[rule_key] = by_rule.get(rule_key, 0) + 1
        if filled < 12:
            print(f"  #{r['target_id']:>5} {d} ← {rule}｜{(r['title'] or '')[:36]}")
        if not args.dry_run:
            conn.execute(
                "UPDATE platform_targets SET target_date=? WHERE target_id=?",
                (d, r["target_id"]),
            )
        filled += 1
    if not args.dry_run:
        conn.commit()
    print(f"\n✓ 補上 {filled} 筆 target_date（規則分布 {by_rule}）")
    conn.close()


if __name__ == "__main__":
    main()
