"""
從 votedata.zip 解析總統選舉的鄉鎮市區層級得票，寫入 township_results。

執行：
  python scripts/import_presidential_by_township.py            # 所有年份
  python scripts/import_presidential_by_township.py --year 113 # 單年
  python scripts/import_presidential_by_township.py --dry-run
"""
import argparse
import csv
import io
import re
import sqlite3
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"
ZIP_PATH = ROOT / "data" / "votedata.zip"

TOTAL_BIG5 = "┴`▓╬"
NINTH_BIG5 = "9Ñ⌠┴`▓╬"


def find_pres_dirs(zf, year_filter):
    found = {}
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
        existing = found.get(ad_year)
        if existing:
            ex_parent = existing.rsplit("/", 2)[-2]
            new_parent = f.rsplit("/", 2)[-2]
            if ex_parent != TOTAL_BIG5 and new_parent == TOTAL_BIG5:
                found[ad_year] = parent_dir
            continue
        found[ad_year] = parent_dir
    return found


def load_areas(zf, dir_path):
    """讀 elbase.csv 取得 (c0, c1, c2) → 名稱對應。
    c2 == '00' 表示縣市層級，c2 != '00' 表示鄉鎮市區層級。
    回傳：
      counties: dict[(c0,c1)] → 縣市中文名
      townships: dict[(c0,c1,c2)] → 鄉鎮市區中文名
    """
    base_path = f"{dir_path}/elbase.csv"
    if base_path not in set(zf.namelist()):
        return {}, {}
    with zf.open(base_path) as fp:
        raw = fp.read()
    for enc in ("utf-8", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return {}, {}

    # 欄位：c0, c1, c2, dept, li, name
    counties = {}
    townships = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 6:
            continue
        c0 = row[0].strip().strip("'")
        c1 = row[1].strip().strip("'")
        c2 = row[2].strip().strip("'")
        dept = row[3].strip().strip("'")
        li = row[4].strip().strip("'")
        name = row[5].strip().strip('"').strip()
        if not name or name in ("全國", "臺灣省", "福建省"):
            continue
        if dept == "000" and li == "0000":
            if (c0, c1) not in counties:
                counties[(c0, c1)] = name
        elif li == "0000":
            # 鄉鎮層級：忽略 c2（elctks 有時用 c2 標 sub-category）
            townships[(c0, c1, dept)] = name
    return counties, townships


def aggregate(zf, dir_path):
    """讀 elctks.csv，回傳 {(c0,c1,c2): {cand_num: votes}}。"""
    path = f"{dir_path}/elctks.csv"
    with zf.open(path) as fp:
        raw = fp.read()
    for enc in ("big5", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return {}
    text = text.replace("\r", "")
    # 欄位：c0, c1, c2, dept, li, polling_stn, cand_num, votes, pct, elected_flag
    by_area = defaultdict(lambda: defaultdict(int))
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 8:
            continue
        c0 = row[0].strip().strip("'")
        c1 = row[1].strip().strip("'")
        c2 = row[2].strip().strip("'")
        dept = row[3].strip().strip("'") if len(row) > 3 else "000"
        try:
            cand_num = int(row[6].strip().strip("'") or "0")
            votes = int(row[7].strip().strip("'") or "0")
        except ValueError:
            continue
        if c0 == "00" or dept == "000":
            continue
        by_area[(c0, c1, dept)][cand_num] += votes
    return by_area


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", help="民國年（例如 113）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    with zipfile.ZipFile(ZIP_PATH) as zf:
        found = find_pres_dirs(zf, args.year)
        print(f"📋 找到 {len(found)} 年份")

        for ad_year, dir_path in sorted(found.items()):
            print(f"\n=== {ad_year} 總統 ===")
            election = conn.execute(
                "SELECT election_id FROM elections "
                "WHERE type='presidential' AND date LIKE ?",
                (f"{ad_year}-%",),
            ).fetchone()
            if not election:
                print("  ✗ 找不到 election")
                continue
            election_id = election["election_id"]

            counties, townships = load_areas(zf, dir_path)
            print(f"  {len(counties)} 縣市 / {len(townships)} 鄉鎮")

            data = aggregate(zf, dir_path)
            print(f"  {len(data)} 鄉鎮投票區")

            # 全國總票數 → cand_num 對應 candidate_ids
            national_totals = defaultdict(int)
            for vbc in data.values():
                for cn, v in vbc.items():
                    national_totals[cn] += v

            existing = conn.execute(
                "SELECT er.candidate_id, c.name, er.votes "
                "FROM election_results er "
                "JOIN candidates c ON er.candidate_id = c.candidate_id "
                "WHERE er.election_id = ? AND er.district = '全國' "
                "ORDER BY er.votes DESC",
                (election_id,),
            ).fetchall()
            if not existing:
                # fallback to 地區(0, 0, 0)
                existing = conn.execute(
                    "SELECT er.candidate_id, c.name, er.votes "
                    "FROM election_results er "
                    "JOIN candidates c ON er.candidate_id = c.candidate_id "
                    "WHERE er.election_id = ? AND er.district LIKE '地區%' "
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

            cn_to_cids = {}
            cn_sorted = sorted(national_totals.keys(), key=lambda c: -national_totals[c])
            for i, cn in enumerate(cn_sorted):
                if i < len(groups):
                    cn_to_cids[cn] = [g["candidate_id"] for g in groups[i]]

            inserted = updated = unmapped_votes = 0
            for (c0, c1, dept), votes_by_cn in data.items():
                county = counties.get((c0, c1))
                township = townships.get((c0, c1, dept))
                if not county or not township:
                    unmapped_votes += sum(votes_by_cn.values())
                    continue
                for cn, total in votes_by_cn.items():
                    cids = cn_to_cids.get(cn, [])
                    for cid in cids:
                        if args.dry_run:
                            continue
                        ex = conn.execute(
                            "SELECT township_result_id, votes FROM township_results "
                            "WHERE election_id=? AND candidate_id=? AND county=? AND township=?",
                            (election_id, cid, county, township),
                        ).fetchone()
                        if ex:
                            if ex["votes"] != total:
                                conn.execute(
                                    "UPDATE township_results SET votes=? WHERE township_result_id=?",
                                    (total, ex["township_result_id"]),
                                )
                                updated += 1
                        else:
                            conn.execute(
                                "INSERT INTO township_results "
                                "(election_id, candidate_id, county, township, votes) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (election_id, cid, county, township, total),
                            )
                            inserted += 1

            if not args.dry_run:
                conn.commit()
                print(f"  ✓ 新增 {inserted}、更新 {updated}")
                if unmapped_votes:
                    print(f"  ⚠️  {unmapped_votes} 票未對應")

    conn.close()
    print("\n完成")


if __name__ == "__main__":
    main()
