"""
從 votedata.zip 重新匯入 2008/2012/2016/2020/2024 區域立委、山地原住民、
平地原住民選舉的票數，取代既有 election_results 中 4x 膨脹的資料。

只取 dept='000', li='0000' 的「選區彙總列」。

執行：
  python scripts/reimport_legislative_votes.py
"""
import csv
import io
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"
ZIP_PATH = ROOT / "data" / "votedata.zip"


def decoded(name: str) -> str:
    try:
        return name.encode("cp437").decode("big5")
    except Exception:
        return name


def read_csv(zf, path: str, prefer_enc: str = "big5") -> list[list[str]]:
    raw = zf.read(path)
    for enc in (prefer_enc, "utf-8", "big5", "cp950"):
        try:
            return list(csv.reader(io.StringIO(raw.decode(enc))))
        except UnicodeDecodeError:
            continue
    return []


def find_path(zf, *substrings: str, suffix: str) -> str | None:
    for n in zf.namelist():
        d = decoded(n)
        if all(s in d for s in substrings) and n.endswith(suffix):
            return n
    return None


def load_county_names(zf, base_path: str) -> dict[tuple[str, str], str]:
    """elbase.csv → (c0, c1) → 縣市名 (dept='000', li='0000')"""
    rows = read_csv(zf, base_path, prefer_enc="utf-8")
    out = {}
    for row in rows:
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


def load_district_names(zf, base_path: str) -> dict[tuple[str, str, str], str]:
    """elbase.csv → (c0, c1, c2) → 選區名 (dept='000', li='0000', c2!='00')
    區域立委：c2 = '01'..'12' 表示第N選區
    """
    rows = read_csv(zf, base_path, prefer_enc="utf-8")
    out = {}
    for row in rows:
        if len(row) < 6:
            continue
        c0 = row[0].strip().strip("'")
        c1 = row[1].strip().strip("'")
        c2 = row[2].strip().strip("'")
        dept = row[3].strip().strip("'")
        li = row[4].strip().strip("'")
        name = row[5].strip().strip('"').strip()
        if dept == "000" and li == "0000" and c2 != "00" and name:
            out[(c0, c1, c2)] = name
    return out


def load_candidates(zf, cand_path: str) -> dict[tuple[str, str, str, str], str]:
    """elcand.csv → (c0, c1, c2, cand_num) → 候選人姓名"""
    rows = read_csv(zf, cand_path, prefer_enc="utf-8")
    out = {}
    for row in rows:
        if len(row) < 7:
            continue
        c0 = row[0].strip().strip("'")
        c1 = row[1].strip().strip("'")
        c2 = row[2].strip().strip("'")
        cand_num = row[5].strip().strip("'")
        name = row[6].strip().strip('"').strip()
        if name:
            out[(c0, c1, c2, cand_num)] = name
    return out


def load_district_totals(zf, ctks_path: str) -> dict[tuple[str, str, str, str], tuple[int, int]]:
    """elctks.csv → (c0, c1, c2, cand_num) → (votes, elected)
    僅取 dept='000', li='0000' 的選區彙總列"""
    rows = read_csv(zf, ctks_path, prefer_enc="big5")
    out = {}
    for row in rows:
        if len(row) < 10:
            continue
        c0 = row[0].strip().strip("'")
        c1 = row[1].strip().strip("'")
        c2 = row[2].strip().strip("'")
        dept = row[3].strip().strip("'")
        li = row[4].strip().strip("'")
        if dept != "000" or li != "0000":
            continue
        cand_num = row[6].strip().strip("'")
        try:
            votes = int(row[7].strip().strip("'") or 0)
        except ValueError:
            continue
        elected_flag = row[9].strip()
        elected = 1 if elected_flag == "*" else 0
        out[(c0, c1, c2, cand_num)] = (votes, elected)
    return out


def format_district(c0: str, c1: str, c2: str, counties: dict, sub_names: dict) -> str:
    """組合選區名。elbase 中 sub_name 已包含縣市名（'臺北市第07選區'），
    直接回傳 sub_name 即可。"""
    sub = sub_names.get((c0, c1, c2))
    if sub:
        return sub
    county = counties.get((c0, c1))
    return county or f"地區({c0}, {c1}, {c2})"


# (election_id, [path-match-keywords])
JOBS = [
    # 區域立委：每縣市拆成多個選區，每選區彙總列是正確總票
    (15, "2008立委", ["/區域/"]),
    (27, "20120114", ["區域立委"]),
    (45, "2020總統立委", ["區域立委"]),
    (51, "2024總統立委", ["區域立委"]),
    # 山地/平地原住民立委：原本是 district='全國' 單一橫排，已正確不需重 import
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    with zipfile.ZipFile(ZIP_PATH) as zf:
        for election_id, year_key, scopes in JOBS:
            print(f"\n=== election_id={election_id} {year_key} {scopes} ===")
            base_path = find_path(zf, year_key, *scopes, suffix="/elbase.csv")
            ctks_path = find_path(zf, year_key, *scopes, suffix="/elctks.csv")
            cand_path = find_path(zf, year_key, *scopes, suffix="/elcand.csv")
            if not all([base_path, ctks_path, cand_path]):
                print(f"  ✗ 路徑找不到")
                continue

            counties = load_county_names(zf, base_path)
            sub_names = load_district_names(zf, base_path)
            cands = load_candidates(zf, cand_path)
            totals = load_district_totals(zf, ctks_path)
            print(f"  {len(counties)} 縣市 / {len(sub_names)} 選區 / {len(cands)} 候選人 / {len(totals)} 票")

            updated = inserted = unmatched = 0
            for (c0, c1, c2, cn), (votes, elected) in totals.items():
                name = cands.get((c0, c1, c2, cn))
                if not name:
                    unmatched += 1
                    continue
                district = format_district(c0, c1, c2, counties, sub_names)
                row = conn.execute(
                    "SELECT candidate_id FROM candidates "
                    "WHERE election_id=? AND name=?",
                    (election_id, name),
                ).fetchone()
                if not row:
                    unmatched += 1
                    continue
                cid = row["candidate_id"]
                # 用 candidate_id 找該候選人此次選舉的 row，但避免 UNIQUE 衝突：
                # 若已有同 district 的 row → UPDATE 它；否則找任一 row UPDATE。
                ex = conn.execute(
                    "SELECT result_id FROM election_results "
                    "WHERE election_id=? AND candidate_id=? AND district=?",
                    (election_id, cid, district),
                ).fetchone() or conn.execute(
                    "SELECT result_id FROM election_results "
                    "WHERE election_id=? AND candidate_id=?",
                    (election_id, cid),
                ).fetchone()
                if ex:
                    try:
                        conn.execute(
                            "UPDATE election_results SET district=?, votes=?, elected=? "
                            "WHERE result_id=?",
                            (district, votes, elected, ex["result_id"]),
                        )
                        updated += 1
                    except sqlite3.IntegrityError:
                        unmatched += 1
                else:
                    try:
                        conn.execute(
                            "INSERT INTO election_results "
                            "(election_id, candidate_id, district, votes, elected) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (election_id, cid, district, votes, elected),
                        )
                        inserted += 1
                    except sqlite3.IntegrityError:
                        unmatched += 1
            conn.commit()
            print(f"  ✓ 更新 {updated}，新增 {inserted}，未對應 {unmatched}")

    conn.close()
    print("\n完成")


if __name__ == "__main__":
    main()
