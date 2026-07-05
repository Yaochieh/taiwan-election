"""2026 地方選舉候選人匯入（P1，roadmap_2026H2.md）。

時程（中選會第622次委員會議公告）：
  08-31 ~ 09-04  受理登記（此階段名單非正式，--stage registered）
  11-12          公告直轄市長候選人名單（--stage official）
  11-17          公告縣市長/直轄市議員/縣市議員名單
  11-28          投開票（票數匯入用既有 import_votedata.py）

對應 elections（已在 DB）：
  77 第5屆直轄市市長 / 78 第21屆縣市長 / 79-81 直轄市議員 / 82 縣市議員

資料來源優先序：
  1. 中選會選舉資料庫 https://db.cec.gov.tw （公告後有結構化名單）
  2. 中選會新聞稿 / 各直轄市縣市選委會公告（登記階段）

用法：
  python scripts/import_2026_candidates.py --stage registered --csv 登記名單.csv --dry-run
  python scripts/import_2026_candidates.py --stage official  --csv 公告名單.csv

CSV 欄位（自行整理或從 db.cec.gov.tw 匯出）：
  election_id, name, party, district
  （registered 階段可另加 note 欄）

防呆：
  - registered 階段寫入的 candidate 會在 background 標 [登記中未經審定]，
    official 階段重跑會清掉此標記並比對差異（退選/資格不符者列出）
  - 一律 dry-run 先看 diff，資料標來源（--source-url 必填）
"""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"

VALID_ELECTIONS = {77, 78, 79, 80, 81, 82}
REG_MARK = "[登記中未經審定]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["registered", "official"], required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--source-url", required=True,
                    help="名單來源（中選會資料庫/公告 URL），資料一定標來源")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.csv, encoding="utf-8-sig")))
    if not rows:
        sys.exit("✗ CSV 是空的")
    need = {"election_id", "name", "party", "district"}
    if not need.issubset(rows[0].keys()):
        sys.exit(f"✗ CSV 缺欄位：{need - set(rows[0].keys())}")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    n_new = n_exist = 0
    for r in rows:
        eid = int(r["election_id"])
        if eid not in VALID_ELECTIONS:
            sys.exit(f"✗ election_id {eid} 不是 2026 場次（77-82）")
        # 政黨：找既有，找不到列警告（不自動建黨，避免打錯字產生新政黨）
        party_id = None
        if r["party"].strip():
            p = conn.execute("SELECT party_id FROM parties WHERE name=?",
                             (r["party"].strip(),)).fetchone()
            if p:
                party_id = p["party_id"]
            else:
                print(f"  ⚠ 政黨「{r['party']}」不在 parties 表，{r['name']} 先以無黨籍寫入，請人工確認")
        exist = conn.execute(
            "SELECT candidate_id FROM candidates WHERE name=? AND election_id=?",
            (r["name"].strip(), eid)).fetchone()
        if exist:
            n_exist += 1
            continue
        n_new += 1
        bg = REG_MARK if args.stage == "registered" else None
        print(f"  + e{eid} {r['district']} {r['name']}（{r['party'] or '無黨籍'}）"
              f"{' ' + REG_MARK if bg else ''}")
        if not args.dry_run:
            conn.execute(
                """INSERT INTO candidates (name, party_id, election_id, district, background)
                   VALUES (?, ?, ?, ?, ?)""",
                (r["name"].strip(), party_id, eid, r["district"].strip(), bg))

    # official 階段：清登記標記 + 找出登記過但不在正式名單的（退選/未通過審定）
    if args.stage == "official" and not args.dry_run:
        official_names = {(int(r["election_id"]), r["name"].strip()) for r in rows}
        dropped = [
            (row["name"], row["election_id"]) for row in conn.execute(
                "SELECT name, election_id FROM candidates "
                "WHERE election_id IN (77,78,79,80,81,82) AND background=?", (REG_MARK,))
            if (row["election_id"], row["name"]) not in official_names
        ]
        conn.execute("UPDATE candidates SET background=NULL "
                     "WHERE election_id IN (77,78,79,80,81,82) AND background=?", (REG_MARK,))
        for name, eid in dropped:
            print(f"  ✗ {name}（e{eid}）登記過但不在正式名單（退選/未通過審定），請人工處理")

    if not args.dry_run:
        conn.commit()
    print(f"\n✓ 新增 {n_new}、已存在略過 {n_exist}（來源：{args.source_url}）")
    print("  下一步：11月中公報上架後跑 OCR 管線（見 scripts/README.md）")
    conn.close()


if __name__ == "__main__":
    main()
