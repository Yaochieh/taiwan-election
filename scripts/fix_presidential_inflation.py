"""修總統選舉縣市列 4x / 鄉鎮列 3x 膨脹。

原因：import_presidential_by_county/township 把 elctks.csv 所有層級
（縣市摘要+鄉鎮摘要+村里+投開票所）全部 SUM，縣市多算 4 次、鄉鎮 3 次。
2000/2004 有驗票修正，除以 4 會差幾百票，所以直接用官方「摘要列」覆寫：
- 縣市摘要列：c2..c5 全零、(c0,c1) 非全國
- 鄉鎮摘要列：c2 非零、c4/c5 全零

候選人對應：DB「全國」列票數 == zip 全國摘要列票數（正副同票同組）。

用法：python scripts/fix_presidential_inflation.py [--dry-run]
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
DB = ROOT / "data" / "db.sqlite"
ZIP = ROOT / "data" / "votedata.zip"
TOTAL = "┴`▓╬"
NINTH = "9Ñ⌠┴`▓╬"


def find_pres_dirs(zf):
    found = {}
    for f in zf.namelist():
        if not f.endswith("/elctks.csv") or TOTAL not in f:
            continue
        m = re.search(r"/((?:19|20)\d{2})", f)
        ad = int(m.group(1)) if m else (1996 if NINTH in f else None)
        if ad is None:
            continue
        parent = f.rsplit("/", 1)[0]
        base = parent.split("/")[-1]
        ex = found.get(ad)
        if ex is None or (ex.split("/")[-1] != TOTAL and (base == TOTAL or NINTH in base)):
            found[ad] = parent
    return found


def decode(raw):
    for enc in ("big5", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("big5", errors="replace")


def load_names(zf, dirp):
    """elbase.csv → 縣市 {(c0,c1): name}、鄉鎮 {(c0,c1,dept): name}

    elbase 格式：prv, city, area(恆00), dept, li, ..., name
    縣市列 dept=000 li=0000；鄉鎮列 dept=010 li=0000；村里列 li 非零。
    """
    text = decode(zf.open(dirp + "/elbase.csv").read())
    county, township = {}, {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 6:
            continue
        c = [x.strip().strip("'") for x in row[:6]]
        name = row[-1].strip().strip('"').strip()
        if not name:
            continue
        try:
            dept, li = int(c[3] or 0), int(c[4] or 0)
        except ValueError:
            continue
        if li:
            continue
        if dept == 0:
            if name not in ("全國", "臺灣省", "福建省"):
                county.setdefault((c[0], c[1]), name)
        else:
            township.setdefault((c[0], c[1], c[3]), name)
    return county, township


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    zf = zipfile.ZipFile(ZIP)
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row

    tot_c = tot_t = 0
    for ad, dirp in sorted(find_pres_dirs(zf).items()):
        text = decode(zf.open(dirp + "/elctks.csv").read()).replace("\r", "")
        cmap, tmap = load_names(zf, dirp)
        county_sum = defaultdict(dict)    # name -> {cand_num: votes}
        township_sum = defaultdict(dict)  # (county, township) -> {cand_num: votes}
        national = {}
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 8:
                continue
            c = [x.strip().strip("'") for x in row[:8]]
            try:
                a2, a3, a4, a5 = (int(c[i] or 0) for i in (2, 3, 4, 5))
                cn, v = int(c[6] or 0), int(c[7] or 0)
            except ValueError:
                continue
            if a4 or a5:
                continue  # 村里/投開票所層級
            # elctks 格式：prv, city, 選區(a2), dept(a3=鄉鎮), li, tbox
            if a3 == 0:
                if int(c[0] or 0) == 0:
                    national[cn] = v
                elif (c[0], c[1]) in cmap:
                    county_sum[cmap[(c[0], c[1])]][cn] = v
            else:
                key = (c[0], c[1], c[3])
                if key in tmap and (c[0], c[1]) in cmap:
                    township_sum[(cmap[(c[0], c[1])], tmap[key])][cn] = v

        el = conn.execute("SELECT election_id FROM elections WHERE type='presidential' AND date LIKE ?",
                          (f"{ad}-%",)).fetchone()
        if not el:
            print(f"{ad}: DB 無對應選舉，跳過")
            continue
        eid = el["election_id"]
        v2cids = defaultdict(list)
        for r in conn.execute("SELECT candidate_id, votes FROM election_results "
                              "WHERE election_id=? AND (district='全國' OR district LIKE '地區(0%')", (eid,)):
            v2cids[r["votes"]].append(r["candidate_id"])
        cn2cids = {cn: v2cids.get(v, []) for cn, v in national.items()}
        if any(not cids for cids in cn2cids.values()):
            print(f"{ad} (e{eid}): 有 cand_num 對不上全國票數，跳過不動")
            continue

        nc = nt = 0
        for name, cd in county_sum.items():
            for cn, v in cd.items():
                for cid in cn2cids[cn]:
                    cur = conn.execute("SELECT result_id, votes FROM election_results "
                                       "WHERE election_id=? AND candidate_id=? AND district=?",
                                       (eid, cid, name)).fetchone()
                    if cur and cur["votes"] != v:
                        if not args.dry_run:
                            conn.execute("UPDATE election_results SET votes=? WHERE result_id=?",
                                         (v, cur["result_id"]))
                        nc += 1
        for (cname, tname), cd in township_sum.items():
            for cn, v in cd.items():
                for cid in cn2cids[cn]:
                    cur = conn.execute("SELECT township_result_id, votes FROM township_results "
                                       "WHERE election_id=? AND candidate_id=? AND county=? AND township=?",
                                       (eid, cid, cname, tname)).fetchone()
                    if cur and cur["votes"] != v:
                        if not args.dry_run:
                            conn.execute("UPDATE township_results SET votes=? WHERE township_result_id=?",
                                         (v, cur["township_result_id"]))
                        nt += 1
        if not args.dry_run:
            conn.commit()
        # 驗證：縣市加總 == 全國列
        chk = conn.execute("""
            SELECT ROUND(CAST(SUM(CASE WHEN district!='全國' AND district NOT LIKE '地區(0%' THEN votes ELSE 0 END) AS REAL)
              / NULLIF(SUM(CASE WHEN district='全國' OR district LIKE '地區(0%' THEN votes ELSE 0 END),0), 3) FROM election_results
            WHERE election_id=?""", (eid,)).fetchone()[0]
        print(f"{ad} (e{eid}): 縣市修 {nc} 筆、鄉鎮修 {nt} 筆 → 縣市加總/全國 = {chk}")
        tot_c += nc
        tot_t += nt
    conn.close()
    print(f"\n共修縣市 {tot_c} 筆、鄉鎮 {tot_t} 筆")


if __name__ == "__main__":
    main()
