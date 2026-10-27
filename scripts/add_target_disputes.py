"""旗艦承諾「官方數字口徑爭議」標註（2026-09 使用者回饋 R2，2026-10-27 定案）。

只收人工審過的異議來源。輸入 JSON（陣列），每筆：
  {
    "target_id": 31,
    "source_type": "oversight" | "factcheck" | "ngo" | "media",
    "publisher": "審計部",
    "title": "113年度中央政府總決算審核報告",
    "url": "https://...",
    "quote": "原文照抄的引句",
    "published_at": "2025-08-01",       # 選填
    "note": "選填說明"
  }

收錄條件（docs/roadmap_2026H2.md「回饋 R2 決定」）：
  - 必須針對該數字或口徑本身；不收社論、評論、政黨或政治人物聲明
  - 只限旗艦承諾（platform_targets.flagship = 1）
  - quote 必須是原文照抄 —— 寫入前會抓 url 比對，原文裡找不到就拒絕

用法：
  python scripts/add_target_disputes.py disputes.json --dry-run
  python scripts/add_target_disputes.py disputes.json
  # 網站擋爬蟲、已由人工開網頁核對過引句時：
  python scripts/add_target_disputes.py disputes.json --manual-verified 3,7
"""
import argparse
import html
import json
import re
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"

SOURCE_TYPES = {"oversight", "factcheck", "ngo", "media"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_target_disputes (
    dispute_id     INTEGER PRIMARY KEY,
    target_id      INTEGER NOT NULL REFERENCES platform_targets(target_id) ON DELETE CASCADE,
    source_type    TEXT NOT NULL CHECK (source_type IN ('oversight','factcheck','ngo','media')),
    publisher      TEXT NOT NULL,
    title          TEXT,
    url            TEXT NOT NULL,
    quote          TEXT NOT NULL,
    published_at   DATE,
    retrieved_at   DATE NOT NULL,
    quote_verified TEXT NOT NULL CHECK (quote_verified IN ('auto','manual')),  -- auto=抓網頁比對；manual=人工開網頁核對
    note           TEXT,
    UNIQUE(target_id, url)
)
"""


def normalize(s: str) -> str:
    """比對用：去掉空白與常見標點差異（全形／半形），只留字。"""
    s = html.unescape(s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"[\s，,。．.、：:；;「」『』\"'“”‘’（）()！!？?…—\-]", "", s)


def page_text(url: str) -> str | None:
    """用 curl 抓網頁（政府站常擋 python UA），失敗回 None。PDF 不處理，交給 --manual-verified。"""
    try:
        r = subprocess.run(
            ["curl", "-sL", "-m", "40", "-A", "Mozilla/5.0", url],
            capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0 or not r.stdout or r.stdout[:4] == b"%PDF":
        return None
    return r.stdout.decode("utf-8", errors="ignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--manual-verified", default="",
                    help="逗號分隔的資料序號（從 1 起算），表示已人工開網頁核對引句，略過自動比對")
    args = ap.parse_args()
    manual = {int(x) for x in args.manual_verified.split(",") if x.strip()}

    items = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(SCHEMA)
    today = date.today().isoformat()

    ok = rejected = 0
    for i, d in enumerate(items, 1):
        tag = f"[{i}] target {d.get('target_id')} {d.get('publisher')}"
        missing = [k for k in ("target_id", "source_type", "publisher", "url", "quote") if not d.get(k)]
        if missing:
            print(f"✗ {tag}: 缺欄位 {missing}"); rejected += 1; continue
        if d["source_type"] not in SOURCE_TYPES:
            print(f"✗ {tag}: source_type 必須是 {sorted(SOURCE_TYPES)}"); rejected += 1; continue
        t = conn.execute("SELECT flagship FROM platform_targets WHERE target_id=?",
                         (d["target_id"],)).fetchone()
        if not t or t[0] != 1:
            print(f"✗ {tag}: 不是旗艦承諾"); rejected += 1; continue
        if len(normalize(d["quote"])) < 10:
            print(f"✗ {tag}: 引句太短，無法確認是在講這個數字"); rejected += 1; continue

        if i in manual:
            verified = "manual"
        else:
            text = page_text(d["url"])
            if text is None:
                print(f"✗ {tag}: 抓不到網頁（或是 PDF）。人工核對引句後用 --manual-verified {i}")
                rejected += 1; continue
            if normalize(d["quote"]) not in normalize(text):
                print(f"✗ {tag}: 網頁原文找不到這段引句 —— 必須照抄，不可改寫")
                rejected += 1; continue
            verified = "auto"

        print(f"✓ {tag}（{verified}）")
        ok += 1
        if not args.dry_run:
            conn.execute(
                """INSERT INTO platform_target_disputes
                   (target_id, source_type, publisher, title, url, quote, published_at,
                    retrieved_at, quote_verified, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(target_id, url) DO UPDATE SET
                     source_type=excluded.source_type, publisher=excluded.publisher,
                     title=excluded.title, quote=excluded.quote,
                     published_at=excluded.published_at, retrieved_at=excluded.retrieved_at,
                     quote_verified=excluded.quote_verified, note=excluded.note""",
                (d["target_id"], d["source_type"], d["publisher"].strip(), d.get("title"),
                 d["url"].strip(), d["quote"].strip(), d.get("published_at"), today,
                 verified, d.get("note")))
    if not args.dry_run:
        conn.commit()
    conn.close()
    print(f"\n通過 {ok}、拒絕 {rejected}{'（dry-run 未寫入）' if args.dry_run else ''}")
    sys.exit(1 if rejected else 0)


if __name__ == "__main__":
    main()
