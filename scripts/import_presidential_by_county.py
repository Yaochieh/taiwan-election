"""
從 votedata.zip 解析總統選舉的縣市層級得票，新增進 election_results。

之前 import 把所有縣市票加總成「全國」一筆，本腳本恢復縣市分布。

執行：
  python scripts/import_presidential_by_county.py            # 所有年份
  python scripts/import_presidential_by_county.py --year 113 # 單年
  python scripts/import_presidential_by_county.py --dry-run  # 試跑
"""
import argparse
import csv
import io
import re
import sqlite3
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"
ZIP_PATH = ROOT / "data" / "votedata.zip"

# 「總統」的 Big5 編碼（用於 raw 路徑比對）
TOTAL_BIG5 = "┴`▓╬"


def find_pres_dirs(zf: zipfile.ZipFile, year_filter: str | None) -> dict[int, str]:
    """找各年的總統 elctks.csv 父目錄。"""
    found: dict[int, str] = {}
    # 9任總統 = 1996（首屆民選），路徑沒有西元年
    NINTH_BIG5 = "9Ñ⌠┴`▓╬"
    for f in zf.namelist():
        if not f.endswith("/elctks.csv"):
            continue
        if TOTAL_BIG5 not in f:
            continue
        if "立委" in f or "原住民" in f or "副總統" in f:
            continue
        m = re.search(r"/((?:19|20)\d{2})", f)
        if m:
            ad_year = int(m.group(1))
        elif NINTH_BIG5 in f:
            ad_year = 1996
        else:
            continue
        if year_filter and (int(year_filter) + 1911 != ad_year):
            continue
        parent_dir = f.rsplit("/", 1)[0]
        # 若已記錄、優先取「父目錄純為 總統」深層結構
        existing = found.get(ad_year)
        if existing:
            ex_parent = existing.rsplit("/", 2)[-2]
            new_parent = f.rsplit("/", 2)[-2]
            if ex_parent != TOTAL_BIG5 and new_parent == TOTAL_BIG5:
                found[ad_year] = parent_dir
            continue
        found[ad_year] = parent_dir
    return found


def load_county_map(zf: zipfile.ZipFile, dir_path: str) -> dict[tuple[str, str], str]:
    """從 elbase.csv 抓 (col0, col1) → 縣市中文名。"""
    base_path = f"{dir_path}/elbase.csv"
    if base_path not in set(zf.namelist()):
        return {}
    with zf.open(base_path) as fp:
        raw = fp.read()
    # 試 utf-8 → big5
    for enc in ("utf-8", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return {}

    mapping = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 6:
            continue
        c0 = row[0].strip().strip("'")
        c1 = row[1].strip().strip("'")
        c2 = row[2].strip().strip("'") if len(row) > 2 else ""
        if c2 != "00":
            continue
        name = row[-1].strip().strip('"').strip()
        # 排除「全國」「臺灣省」「福建省」這類非縣市記錄
        if name in ("全國", "臺灣省", "福建省", ""):
            continue
        if (c0, c1) not in mapping:
            mapping[(c0, c1)] = name
    return mapping


def aggregate_votes(zf: zipfile.ZipFile, dir_path: str) -> dict[tuple[str, str], dict[int, int]]:
    """讀 elctks.csv，回傳 {(c0, c1): {cand_num: votes}}。"""
    path = f"{dir_path}/elctks.csv"
    with zf.open(path) as fp:
        raw = fp.read()
    # 嘗試多種編碼
    for enc in ("big5", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return {}
    text = text.replace("\r", "")
    by_county: dict[tuple[str, str], dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 8:
            continue
        c0 = row[0].strip().strip("'")
        c1 = row[1].strip().strip("'")
        try:
            cand_num = int(row[6].strip().strip("'") or "0")
            votes = int(row[7].strip().strip("'") or "0")
        except ValueError:
            continue
        if c0 == "00":
            continue
        by_county[(c0, c1)][cand_num] += votes
    return by_county


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", help="只跑特定民國年（如 113）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    with zipfile.ZipFile(ZIP_PATH) as zf:
        found = find_pres_dirs(zf, args.year)
        print(f"📋 找到 {len(found)} 年份的總統選舉資料")

        for ad_year, dir_path in sorted(found.items()):
            print(f"\n=== {ad_year} 年總統選舉 ===")
            election = conn.execute(
                "SELECT election_id, name FROM elections "
                "WHERE type = 'presidential' AND date LIKE ?",
                (f"{ad_year}-%",),
            ).fetchone()
            if not election:
                print(f"  ✗ DB 找不到對應 election")
                continue
            election_id = election["election_id"]

            county_map = load_county_map(zf, dir_path)
            print(f"  載入 {len(county_map)} 個縣市對應")

            votes_data = aggregate_votes(zf, dir_path)
            print(f"  votes_data 含 {len(votes_data)} 個 (c0,c1) 組合")

            # 全國總票數，用於 cand_num → candidate_id 對應
            national_totals: dict[int, int] = defaultdict(int)
            for vbc in votes_data.values():
                for cn, v in vbc.items():
                    national_totals[cn] += v

            # 從 DB existing 結果反推 cand_num 對應（同票數正副配對）
            # 既有 district 可能是「全國」或「地區(0, 0, 0)」（舊格式）
            existing = conn.execute(
                "SELECT er.candidate_id, c.name, c.background, er.votes "
                "FROM election_results er "
                "JOIN candidates c ON er.candidate_id = c.candidate_id "
                "WHERE er.election_id = ? "
                "AND er.district IN ('全國', '地區(0, 0, 0)') "
                "ORDER BY er.votes DESC",
                (election_id,),
            ).fetchall()
            groups = []
            cur_votes = None
            for r in existing:
                if cur_votes != r["votes"]:
                    groups.append([])
                    cur_votes = r["votes"]
                groups[-1].append(dict(r))

            cn_to_cids: dict[int, list[int]] = {}
            cn_sorted = sorted(national_totals.keys(), key=lambda c: -national_totals[c])
            for i, cn in enumerate(cn_sorted):
                if i < len(groups):
                    cn_to_cids[cn] = [g["candidate_id"] for g in groups[i]]
            print(f"  cand_num → candidate_ids: {cn_to_cids}")

            # 寫入 per-county results
            inserted = 0
            updated = 0
            unmapped = 0
            for (c0, c1), votes_by_cn in votes_data.items():
                # 直轄市：c1 == '000'
                # 非直轄市：c0='10' 或 '09'，c1 是 sub-code
                if c1 != "000":
                    county = county_map.get((c0, c1))
                else:
                    county = county_map.get((c0, "000"))

                if not county:
                    unmapped += sum(votes_by_cn.values())
                    continue

                # 用「{county}」純文字當 district（之後也可以加 city code）
                district = county
                for cn, total in votes_by_cn.items():
                    cids = cn_to_cids.get(cn, [])
                    for cid in cids:
                        if args.dry_run:
                            print(f"    [dry] {district} cand={cid} votes={total}")
                            continue
                        ex = conn.execute(
                            "SELECT result_id, votes FROM election_results "
                            "WHERE election_id = ? AND candidate_id = ? AND district = ?",
                            (election_id, cid, district),
                        ).fetchone()
                        if ex:
                            if ex["votes"] != total:
                                conn.execute(
                                    "UPDATE election_results SET votes = ? WHERE result_id = ?",
                                    (total, ex["result_id"]),
                                )
                                updated += 1
                        else:
                            conn.execute(
                                "INSERT INTO election_results "
                                "(election_id, candidate_id, district, votes, elected) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (election_id, cid, district, total, 0),
                            )
                            inserted += 1

            if not args.dry_run:
                conn.commit()
                print(f"  ✓ 新增 {inserted} 筆、更新 {updated} 筆")
                if unmapped:
                    print(f"  ⚠️  {unmapped} 票未對應到縣市")

    conn.close()
    print("\n完成")


if __name__ == "__main__":
    main()
