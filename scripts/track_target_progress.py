"""政見量化承諾進度追蹤：寫入 platform_target_progress。

P0 MVP（roadmap_2026H2.md）：把 targets → progress → 開放資料 的斷鏈接起來。
每筆進度記錄必附 source_url（資料一定標來源）。

模式：
  1. 手動記錄（人工查證後寫入，v1 主力）：
     python scripts/track_target_progress.py record <target_id> <current_value> \
         --source-url URL [--note 說明]
  2. 自動抓取（可插拔 fetcher，目前支援北市社宅戰情 API）：
     python scripts/track_target_progress.py fetch taipei_social_housing --target-id 684 [--dry-run]
  3. 列出旗艦承諾與最新進度：
     python scripts/track_target_progress.py list
"""
import argparse
import json
import sqlite3
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"


def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_flagship_column(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(platform_targets)")]
    if "flagship" not in cols:
        conn.execute("ALTER TABLE platform_targets ADD COLUMN flagship INTEGER DEFAULT 0")
        conn.commit()


def record(conn, target_id: int, value: float, source_url: str, note: str | None, dry: bool):
    t = conn.execute(
        "SELECT person_name, title, target_value, metric_unit FROM platform_targets WHERE target_id=?",
        (target_id,),
    ).fetchone()
    if not t:
        sys.exit(f"✗ target_id {target_id} 不存在")
    if not source_url:
        sys.exit("✗ 必須提供 --source-url（資料一定標來源）")
    pct = f"{value / t['target_value'] * 100:.1f}%" if t["target_value"] else "?"
    print(f"  {t['person_name']}｜{t['title']}")
    print(f"  進度 {value} / {t['target_value']} {t['metric_unit'] or ''}（{pct}）")
    print(f"  來源 {source_url}")
    # 數值與最新一筆相同就跳過（每日自動抓取不該累積重複列）
    last = conn.execute(
        "SELECT current_value FROM platform_target_progress WHERE target_id=? "
        "ORDER BY recorded_at DESC LIMIT 1", (target_id,)).fetchone()
    if last is not None and last["current_value"] == value:
        print("  = 數值未變，跳過寫入")
        return
    if dry:
        print("  [dry-run] 未寫入")
        return
    conn.execute(
        """INSERT INTO platform_target_progress
           (target_id, recorded_at, current_value, note, source_url)
           VALUES (?, ?, ?, ?, ?)""",
        (target_id, date.today().isoformat(), value, note, source_url),
    )
    conn.commit()
    print("  ✓ 已寫入 platform_target_progress")


# ── 自動 fetcher（可插拔）───────────────────────────────────────────────────
# 每個 fetcher 回傳 (value, source_url, note)

def fetch_taipei_social_housing() -> tuple[float, str, str]:
    """北市社宅戰情中心 BigData API：加總已完工戶數。"""
    url = "https://hms.udd.gov.taipei/api/BigData/project"
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    rows = data if isinstance(data, list) else data.get("data", data.get("result", []))
    # schema (2026-07 確認): name/distict/houseHolds/progress，progress ∈
    # {已完工, 施工中及待開工, 規劃中, 都更聯開分回}
    done = 0
    n_done = 0
    for p in rows:
        status = str(p.get("progress") or "")
        try:
            units = float(str(p.get("houseHolds") or 0).replace(",", ""))
        except ValueError:
            units = 0
        if "已完工" in status:
            done += units
            n_done += 1
    if done == 0:
        raise RuntimeError(f"API 回傳 {len(rows)} 案但解析不到完工戶數，schema 可能變了: "
                           f"keys={list(rows[0].keys()) if rows else 'empty'}")
    return done, url, f"北市社宅「已完工」{n_done} 案共 {done:.0f} 戶（戰情中心 API 即時值）"


FETCHERS = {
    "taipei_social_housing": fetch_taipei_social_housing,
}


def cmd_list(conn):
    rows = conn.execute("""
        SELECT t.target_id, t.person_name, t.title, t.target_value, t.metric_unit,
               t.flagship,
               (SELECT current_value FROM platform_target_progress pp
                WHERE pp.target_id = t.target_id ORDER BY recorded_at DESC LIMIT 1) AS latest,
               (SELECT recorded_at FROM platform_target_progress pp
                WHERE pp.target_id = t.target_id ORDER BY recorded_at DESC LIMIT 1) AS at
        FROM platform_targets t
        WHERE t.flagship = 1
        ORDER BY t.person_name
    """).fetchall()
    if not rows:
        print("（尚無旗艦承諾，先用 UPDATE platform_targets SET flagship=1 WHERE target_id IN (...)）")
    for r in rows:
        prog = f"{r['latest']} @ {r['at']}" if r["latest"] is not None else "—"
        print(f"  #{r['target_id']:>5} {r['person_name']}｜{r['title'][:36]}"
              f"｜目標 {r['target_value']} {r['metric_unit'] or ''}｜最新 {prog}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_rec = sub.add_parser("record", help="人工查證後記錄進度")
    p_rec.add_argument("target_id", type=int)
    p_rec.add_argument("current_value", type=float)
    p_rec.add_argument("--source-url", required=True)
    p_rec.add_argument("--note")
    p_rec.add_argument("--dry-run", action="store_true")
    p_fetch = sub.add_parser("fetch", help="自動抓取開放資料")
    p_fetch.add_argument("fetcher", choices=sorted(FETCHERS))
    p_fetch.add_argument("--target-id", type=int, required=True)
    p_fetch.add_argument("--dry-run", action="store_true")
    sub.add_parser("list", help="列出旗艦承諾與最新進度")
    args = ap.parse_args()

    conn = get_conn()
    ensure_flagship_column(conn)
    if args.cmd == "list":
        cmd_list(conn)
    elif args.cmd == "record":
        record(conn, args.target_id, args.current_value, args.source_url, args.note, args.dry_run)
    elif args.cmd == "fetch":
        value, url, note = FETCHERS[args.fetcher]()
        record(conn, args.target_id, value, url, note, args.dry_run)
    conn.close()


if __name__ == "__main__":
    main()
