"""資料真實性稽核 — 每次 commit DB 前跑。發現新問題 exit code 1。

檢查：
(a) 模板重複：同一場選舉 ≥3 位候選人 content 前 80 字完全相同（腦補模板特徵）
(b) 潤稿偏離：content 對 content_raw 的 4-gram 重疊 < 60%（潤稿內容不是來自原始 OCR）
(c) content_raw NULL 的政見數（來源缺口）
(d) 有 background 但無 background_source 的候選人數（履歷來源缺口）
(e) status='completed' 但 0 筆結果的選舉

已知遺留記錄在 scripts/audit_baseline.json；只有「超出 baseline」才算新問題。
更新 baseline：python scripts/audit_authenticity.py --update-baseline

用法：python scripts/audit_authenticity.py [--verbose] [--update-baseline]
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"
BASELINE = Path(__file__).parent / "audit_baseline.json"


def _ratio(t: str, s: str) -> float:
    if len(t) < 4:
        return 1.0  # 太短不判
    grams = [t[i:i+4] for i in range(len(t) - 3)]
    return sum(1 for g in grams if g in s) / len(grams) if grams else 1.0


def overlap_ratio(text: str, source: str) -> float:
    t = re.sub(r"[\s\d。，、：（）()【】「」\.]", "", text)
    s = re.sub(r"[\s\d。，、：（）()【】「」\.]", "", source)
    # 某些公報 OCR 每字重複(「顛顛覆覆」)，取「原樣」與「連續重複字壓縮」兩者較高的重疊度
    dedup = re.compile(r"(.)\1+")
    return max(_ratio(t, s), _ratio(dedup.sub(r"\1", t), dedup.sub(r"\1", s)))


def run_checks(conn, verbose=False):
    findings = {}

    # (a) 模板重複
    rows = conn.execute(
        "SELECT election_id, platform_id, candidate_id, substr(content,1,80) AS head "
        "FROM platforms WHERE length(content) >= 80").fetchall()
    groups = defaultdict(list)
    for r in rows:
        groups[(r["election_id"], r["head"])].append(r["platform_id"])
    dup = {f"e{k[0]}:{v[0]}": v for k, v in groups.items() if len(v) >= 3}
    findings["a_template_dup"] = sorted(pid for pids in dup.values() for pid in pids)
    if verbose and dup:
        for key, pids in dup.items():
            print(f"  [a] 模板重複 {key}: platforms {pids}")

    # (b) 潤稿偏離原始 OCR
    off = []
    for r in conn.execute(
            "SELECT platform_id, content, content_raw FROM platforms "
            "WHERE content_raw IS NOT NULL AND length(content_raw) >= 200 "
            "AND content != content_raw AND length(content) >= 30").fetchall():
        ratio = overlap_ratio(r["content"], r["content_raw"])
        if ratio < 0.60:
            off.append(r["platform_id"])
            if verbose:
                print(f"  [b] platform {r['platform_id']} 重疊 {ratio:.0%}")
    findings["b_content_off_raw"] = sorted(off)

    # (c) content_raw NULL
    findings["c_raw_null"] = conn.execute(
        "SELECT COUNT(*) FROM platforms WHERE content_raw IS NULL").fetchone()[0]

    # (d) background 無來源
    findings["d_bio_unsourced"] = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE length(COALESCE(background,'')) > 10 "
        "AND length(COALESCE(background_source,'')) = 0").fetchone()[0]

    # (e) completed 但 0 結果
    findings["e_completed_no_results"] = [r[0] for r in conn.execute(
        "SELECT e.election_id FROM elections e WHERE e.status='completed' "
        "AND NOT EXISTS (SELECT 1 FROM election_results er WHERE er.election_id=e.election_id) "
        "AND NOT EXISTS (SELECT 1 FROM recall_results rr WHERE rr.election_id=e.election_id) "
        "ORDER BY e.election_id").fetchall()]

    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    findings = run_checks(conn, verbose=args.verbose)
    conn.close()

    if args.update_baseline:
        BASELINE.write_text(json.dumps(findings, ensure_ascii=False, indent=2))
        print(f"baseline 已更新 → {BASELINE.name}")
        return 0

    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    problems = []
    for key, val in findings.items():
        base = baseline.get(key, [] if isinstance(val, list) else 0)
        if isinstance(val, list):
            new = sorted(set(val) - set(base))
            fixed = sorted(set(base) - set(val))
            status = f"{len(val)} 筆" + (f"（新增 {new}）" if new else "")
            if new:
                problems.append(f"{key}: 新增 {new}")
            if fixed and args.verbose:
                status += f"（已修 {len(fixed)} 筆，可 --update-baseline）"
        else:
            status = f"{val}" + (f"（baseline {base}）" if val != base else "")
            if val > base:
                problems.append(f"{key}: {base} → {val}")
        print(f"{'✗' if any(p.startswith(key) for p in problems) else '✓'} {key}: {status}")

    if problems:
        print(f"\n❌ {len(problems)} 項新問題，禁止 commit DB：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n✅ 無新問題")
    return 0


if __name__ == "__main__":
    sys.exit(main())
