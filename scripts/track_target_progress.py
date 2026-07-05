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


# 來源網域 → (publisher, source_type, authority_level 1官方/2監督/3媒體/4其他)
_DOMAIN_AUTH: list[tuple[str, tuple[str, str, int]]] = [
    (".gov.tw", ("政府機關", "gov_open_data", 1)),
    (".gov.taipei", ("臺北市政府", "gov_open_data", 1)),
    ("tn.edu.tw", ("臺南市政府教育局", "gov_open_data", 1)),
    ("cna.com.tw", ("中央社", "news", 3)),
    ("udn.com", ("聯合報系", "news", 3)),
    ("ltn.com.tw", ("自由時報", "news", 3)),
    ("cw.com.tw", ("天下雜誌", "news", 3)),
    ("e-info.org.tw", ("環境資訊中心", "news", 3)),
    ("newtalk.tw", ("新頭殼", "news", 3)),
    ("ksnews.com.tw", ("更生日報", "news", 3)),
    ("ctee.com.tw", ("工商時報", "news", 3)),
    ("tfc-taiwan.org.tw", ("台灣事實查核中心", "fact_check", 2)),
    ("takao.kcg.gov.tw", ("高雄市政府", "gov_open_data", 1)),
]


def classify_source(url: str) -> tuple[str, str, int]:
    for dom, meta in _DOMAIN_AUTH:
        if dom in url:
            return meta
    return ("其他來源", "other", 4)


def record(conn, target_id: int, value: float, source_urls: list[str],
           note: str | None, dry: bool):
    t = conn.execute(
        "SELECT person_name, title, target_value, metric_unit FROM platform_targets WHERE target_id=?",
        (target_id,),
    ).fetchone()
    if not t:
        sys.exit(f"✗ target_id {target_id} 不存在")
    if not source_urls:
        sys.exit("✗ 必須提供至少一個 --source-url（資料一定標來源）")
    pct = f"{value / t['target_value'] * 100:.1f}%" if t["target_value"] else "?"
    print(f"  {t['person_name']}｜{t['title']}")
    print(f"  進度 {value} / {t['target_value']} {t['metric_unit'] or ''}（{pct}）")
    for u in source_urls:
        pub, _, lv = classify_source(u)
        print(f"  來源[{pub}·L{lv}] {u}")
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
    cur = conn.execute(
        """INSERT INTO platform_target_progress
           (target_id, recorded_at, current_value, note, source_url)
           VALUES (?, ?, ?, ?, ?)""",
        (target_id, date.today().isoformat(), value, note, source_urls[0]),
    )
    progress_id = cur.lastrowid
    # 全部來源寫入 platform_progress_sources（多來源，含權威分級）
    for u in source_urls:
        pub, stype, lv = classify_source(u)
        conn.execute(
            """INSERT INTO platform_progress_sources
               (progress_id, url, source_type, publisher, authority_level, retrieved_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (progress_id, u, stype, pub, lv),
        )
    conn.commit()
    print(f"  ✓ 已寫入 progress + {len(source_urls)} 個來源")


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


def _get_html(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


MOI_SH_URL = "https://pip.moi.gov.tw/v3/b/SCRB0501.aspx?mode=7"


def _moi_sh_row(label_scope: str, row_label: str) -> tuple[list[int], str]:
    """內政部社宅統計表：取某區域段(label_scope)內某列(row_label)的 6 個數字
    [完工, 興建中, 決標待開工, 達成小計, 規劃中, 總計]，含加總驗算。"""
    import re
    html = _get_html(MOI_SH_URL)
    m_date = re.search(r"截至\s*(\d{4})年(\d{1,2})月(\d{1,2})日", html)
    as_of = (f"{m_date.group(1)}-{int(m_date.group(2)):02d}-{int(m_date.group(3)):02d}"
             if m_date else "?")
    i = html.find(label_scope)
    if i < 0:
        raise RuntimeError(f"找不到區域「{label_scope}」（頁面改版？）")
    seg = html[i:i + 4000]
    cells = re.findall(r"<t[dh][^>]*>\s*([^<]*?)\s*</t[dh]>", seg)
    if row_label not in cells:
        raise RuntimeError(f"「{label_scope}」段找不到列「{row_label}」")
    j = cells.index(row_label)
    vals = [int(c.replace(",", "")) for c in cells[j + 1:j + 7]]
    if vals[0] + vals[1] + vals[2] != vals[3] or vals[3] + vals[4] != vals[5]:
        raise RuntimeError(f"社宅統計表驗算失敗（頁面改版？）: {vals}")
    return vals, as_of


def fetch_moi_social_housing() -> tuple[float, str, str]:
    """全國社宅：直建達成(完工+興建中+決標待開工，全國小計) + 包租代管有效契約。

    口徑與 target 31（賴清德 25 萬戶 = 直建13萬+包代12萬）一致。
    """
    import re
    vals, as_of = _moi_sh_row("合計", "小計")
    text = re.sub(r"<[^>]+>", "", _get_html(MOI_SH_URL))
    m_pd = re.search(r"有效契約[^0-9]*([\d,]+)\s*戶", text)
    if not m_pd:
        raise RuntimeError("找不到包租代管有效契約數")
    baodai = int(m_pd.group(1).replace(",", ""))
    total = vals[3] + baodai
    note = (f"內政部社宅專區統計（截至{as_of}）：直接興建達成{vals[3]:,}戶"
            f"（完工{vals[0]:,}+興建中{vals[1]:,}+決標待開工{vals[2]:,}）"
            f"+包租代管有效契約{baodai:,}戶＝{total:,}戶。口徑同前（達成+有效契約）")
    return float(total), MOI_SH_URL, note


def fetch_taichung_social_housing() -> tuple[float, str, str]:
    """台中市府興辦社宅（target 3297 盧秀燕 1.8 萬戶）：臺中市「地方」列總計。

    口徑：盧政見「持續建置達1.8萬戶」為含規劃中之累計，取總計欄；
    note 揭露分解與規劃中占比。
    """
    vals, as_of = _moi_sh_row("臺中市", "地方")
    note = (f"內政部社宅專區統計（截至{as_of}）臺中市地方興辦：總計{vals[5]:,}戶"
            f"（完工{vals[0]:,}+興建中{vals[1]:,}+決標待開工{vals[2]:,}+規劃中{vals[4]:,}）。"
            f"口徑為其政見「建置」之累計數，含前任期興辦")
    return float(vals[5]), MOI_SH_URL, note


def fetch_moea_renewable_share() -> tuple[float, str, str]:
    """經濟部能源署發電概況頁：再生能源占比（靜態HTML句型解析）。"""
    import re
    url = "https://www.moeaea.gov.tw/ECW/populace/content/Content.aspx?menu_id=14437"
    text = re.sub(r"<[^>]+>", "", _get_html(url))
    # 錨定「再生能源占比由…」句，避免抓到太陽光電/風力等內部占比句
    m = re.search(
        r"再生能源占比由民國\s*\d{2,3}\s*年為\s*[\d.]+\s*[%％]?[，,]?\s*至民國\s*(\d{2,3})\s*年增加為\s*([\d.]+)\s*[%％]",
        text)
    if not m:
        raise RuntimeError("能源署頁面句型變了，找不到再生能源占比")
    year = int(m.group(1)) + 1911
    share = float(m.group(2))
    return share, url, f"能源署發電概況：民國{m.group(1)}年（{year}）再生能源發電占比 {share}%"


FETCHERS = {
    "taipei_social_housing": fetch_taipei_social_housing,
    "moi_social_housing": fetch_moi_social_housing,           # target 31 賴清德社宅
    "taichung_social_housing": fetch_taichung_social_housing, # target 3297 盧秀燕
    "moea_renewable_share": fetch_moea_renewable_share,       # target 813 再生能源
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
    p_rec.add_argument("--source-url", required=True, action="append",
                       help="可重複多次以附多個來源（官方+媒體交叉）")
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
        record(conn, args.target_id, args.current_value, args.source_url, args.note, args.dry_run)  # list
    elif args.cmd == "fetch":
        value, url, note = FETCHERS[args.fetcher]()
        record(conn, args.target_id, value, [url], note, args.dry_run)
    conn.close()


if __name__ == "__main__":
    main()
