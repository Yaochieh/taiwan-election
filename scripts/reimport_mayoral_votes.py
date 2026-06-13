"""
重新從 votedata.zip 匯入 2010/2014/2018 縣市長選舉的得票，
取代既有 election_results 中錯誤的 4x 膨脹資料。

每場選舉只取「縣市彙總列」(dept='000', li='0000', poll='0')
作為單一縣市的總票數，避免重複加總 + station-level 兩種來源。

執行：
  python scripts/reimport_mayoral_votes.py
"""
import csv
import io
import sqlite3
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"
ZIP_PATH = ROOT / "data" / "votedata.zip"


def decoded(name: str) -> str:
    try:
        return name.encode("cp437").decode("big5")
    except Exception:
        return name


def load_county_map(zf, year_key: str, scope_substr: str) -> dict[tuple[str, str], str]:
    """讀 elbase.csv，回傳 (c0, c1) → 縣市名"""
    target = None
    for n in zf.namelist():
        d = decoded(n)
        if year_key in d and scope_substr in d and n.endswith("/elbase.csv"):
            target = n
            break
    if not target:
        return {}
    raw = zf.read(target)
    for enc in ("utf-8", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    out = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 6:
            continue
        c0 = row[0].strip().strip("'")
        c1 = row[1].strip().strip("'")
        dept = row[3].strip().strip("'")
        li = row[4].strip().strip("'")
        name = row[5].strip().strip('"').strip()
        if dept == "000" and li == "0000" and name and name != "全國":
            out[(c0, c1)] = name
    return out


def load_cand_map(zf, year_key: str, scope_substr: str) -> dict[tuple[str, str, str], str]:
    """讀 elcand.csv，回傳 (c0, c1, cand_num) → 候選人姓名"""
    target = None
    for n in zf.namelist():
        d = decoded(n)
        if year_key in d and scope_substr in d and n.endswith("/elcand.csv"):
            target = n
            break
    if not target:
        return {}
    raw = zf.read(target)
    for enc in ("utf-8", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    out = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 7:
            continue
        c0 = row[0].strip().strip("'")
        c1 = row[1].strip().strip("'")
        cand_num = row[5].strip().strip("'")
        name = row[6].strip().strip('"').strip()
        if name:
            out[(c0, c1, cand_num)] = name
    return out


def load_county_totals(zf, year_key: str, scope_substr: str) -> dict[tuple[str, str, str], tuple[int, int]]:
    """從 elctks.csv 抓「縣市彙總列」: (dept='000', li='0000')
    回傳 (c0, c1, cand_num) → (votes, elected)"""
    target = None
    for n in zf.namelist():
        d = decoded(n)
        if year_key in d and scope_substr in d and n.endswith("/elctks.csv"):
            target = n
            break
    if not target:
        return {}
    raw = zf.read(target).decode("big5", errors="replace")
    out = {}
    for row in csv.reader(io.StringIO(raw)):
        if len(row) < 10:
            continue
        c0 = row[0].strip().strip("'")
        c1 = row[1].strip().strip("'")
        dept = row[3].strip().strip("'")
        li = row[4].strip().strip("'")
        # 直轄市彙總: dept=000, li=0000
        if dept != "000" or li != "0000":
            continue
        cand_num = row[6].strip().strip("'")
        try:
            votes = int(row[7].strip().strip("'") or 0)
        except ValueError:
            continue
        elected_flag = row[9].strip()
        elected = 1 if elected_flag == "*" else 0
        out[(c0, c1, cand_num)] = (votes, elected)
    return out


JOBS = [
    # (election_id, year_key, [scope_substrings])
    (24, "20101127", ["/市長/"]),  # 五都 only in 2010, narrow to /市長/
    (33, "2014-103", ["直轄市市長", "縣市市長"]),
    (42, "2018-107", ["直轄市市長", "縣市市長"]),
    (49, "2022-111", ["C1/city", "C1/prv"]),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    with zipfile.ZipFile(ZIP_PATH) as zf:
        for election_id, year_key, scopes in JOBS:
            print(f"\n=== election_id={election_id} ({year_key}) ===")
            cand_map = {}
            county_map = {}
            totals = {}
            for scope in scopes:
                cm = load_county_map(zf, year_key, scope)
                county_map.update(cm)
                nm = load_cand_map(zf, year_key, scope)
                cand_map.update(nm)
                tt = load_county_totals(zf, year_key, scope)
                totals.update(tt)
            print(f"  {len(county_map)} 縣市, {len(cand_map)} 候選人對應, {len(totals)} 票數彙總")

            # 對每位候選人，先用姓名找 DB 中的 candidate_id
            updated = inserted = unmatched = 0
            for (c0, c1, cn), (votes, elected) in totals.items():
                name = cand_map.get((c0, c1, cn))
                county = county_map.get((c0, c1))
                if not name or not county:
                    unmatched += 1
                    continue
                row = conn.execute(
                    "SELECT candidate_id FROM candidates "
                    "WHERE election_id=? AND name=?",
                    (election_id, name),
                ).fetchone()
                if not row:
                    unmatched += 1
                    continue
                cid = row["candidate_id"]
                # 嘗試 UPDATE existing
                ex = conn.execute(
                    "SELECT result_id FROM election_results "
                    "WHERE election_id=? AND candidate_id=?",
                    (election_id, cid),
                ).fetchone()
                if ex:
                    conn.execute(
                        "UPDATE election_results SET district=?, votes=?, elected=? "
                        "WHERE result_id=?",
                        (county, votes, elected, ex["result_id"]),
                    )
                    updated += 1
                else:
                    conn.execute(
                        "INSERT INTO election_results "
                        "(election_id, candidate_id, district, votes, elected) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (election_id, cid, county, votes, elected),
                    )
                    inserted += 1
            conn.commit()
            print(f"  ✓ 更新 {updated}，新增 {inserted}，未對應 {unmatched}")

    conn.close()
    print("\n完成")


if __name__ == "__main__":
    main()
