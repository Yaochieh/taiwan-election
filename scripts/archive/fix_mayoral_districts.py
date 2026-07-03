"""
從 votedata.zip 解析 2014/2018 縣市市長與外島市長的 elcand.csv，
把 election_results 中錯置為「地區(10/9, 0, 0)」的 row 改回正確縣市。

執行：
  python scripts/fix_mayoral_districts.py
"""
import csv
import io
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"
ZIP_PATH = ROOT / "data" / "votedata.zip"

# (election_id, year_prefix, [elcand 路徑識別字])
JOBS = [
    (33, "2014", "2014-103年地方公職人員選舉"),
    (42, "2018", "2018-107年地方公職人員選舉"),
]


def decoded(name: str) -> str:
    try:
        return name.encode("cp437").decode("big5")
    except Exception:
        return name


def load_county_map(zf: zipfile.ZipFile, year_key: str, scope: str) -> dict[tuple[str, str], str]:
    """讀 elbase.csv，回傳 (c0, c1) → 縣市名（dept='000', li='0000'）"""
    target = None
    for n in zf.namelist():
        d = decoded(n)
        if year_key in d and scope in d and n.endswith("/elbase.csv"):
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


def load_candidates(zf: zipfile.ZipFile, year_key: str, scope: str) -> list[tuple[str, str, str]]:
    """讀 elcand.csv，回傳 [(c0, c1, candidate_name), ...]"""
    target = None
    for n in zf.namelist():
        d = decoded(n)
        if year_key in d and scope in d and n.endswith("/elcand.csv"):
            target = n
            break
    if not target:
        return []
    raw = zf.read(target)
    for enc in ("utf-8", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 7:
            continue
        c0 = row[0].strip().strip("'")
        c1 = row[1].strip().strip("'")
        name = row[6].strip().strip('"').strip()
        if name:
            out.append((c0, c1, name))
    return out


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    with zipfile.ZipFile(ZIP_PATH) as zf:
        for election_id, year_key, _root in JOBS:
            print(f"\n=== election_id={election_id} ({year_key}) ===")

            # 從兩個 scope 各撈一次：縣市市長 (code 10) 與 外島
            # 但其實外島也算在縣市市長有時。先試「縣市市長」與「外島」
            name_to_county = {}
            for scope_label in ("縣市市長", "外島"):
                county_map = load_county_map(zf, year_key, scope_label)
                cands = load_candidates(zf, year_key, scope_label)
                for c0, c1, name in cands:
                    county = county_map.get((c0, c1))
                    if county:
                        name_to_county[name] = county
            print(f"  從 elcand 解出 {len(name_to_county)} 位候選人 → 縣市對應")

            # 找錯置 row
            wrong = conn.execute(
                "SELECT er.result_id, er.candidate_id, c.name, er.district, er.votes "
                "FROM election_results er JOIN candidates c ON er.candidate_id=c.candidate_id "
                "WHERE er.election_id=? AND er.district LIKE '地區%'",
                (election_id,),
            ).fetchall()
            print(f"  資料庫中錯置 row: {len(wrong)}")

            fixed = unmatched = 0
            for r in wrong:
                county = name_to_county.get(r["name"])
                if not county:
                    unmatched += 1
                    print(f"    ! 找不到對應：{r['name']} ({r['district']})")
                    continue
                conn.execute(
                    "UPDATE election_results SET district=? WHERE result_id=?",
                    (county, r["result_id"]),
                )
                fixed += 1
            conn.commit()
            print(f"  ✓ 修正 {fixed}，未對應 {unmatched}")

    conn.close()
    print("\n完成")


if __name__ == "__main__":
    main()
