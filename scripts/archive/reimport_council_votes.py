"""
重新匯入縣市議員選舉（2010/2014/2018）票數，修正 4x 膨脹 + elected 標記。

每選區有多席（縣市議員是複數選區制），依該選區 elected 數從 elctks.csv
取出（公報已用 '*' 標當選）。

執行：
  python scripts/reimport_council_votes.py
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


def read_csv(zf, path: str, prefer_enc: str = "big5"):
    raw = zf.read(path)
    for enc in (prefer_enc, "utf-8", "big5", "cp950"):
        try:
            return list(csv.reader(io.StringIO(raw.decode(enc))))
        except UnicodeDecodeError:
            continue
    return []


def find_path(zf, *substrings: str, suffix: str):
    for n in zf.namelist():
        d = decoded(n)
        if all(s in d for s in substrings) and n.endswith(suffix):
            return n
    return None


def load_district_names(zf, base_path: str) -> dict[tuple[str, str, str], str]:
    """elbase → (c0, c1, c2) → 選區名（dept='000', li='0000', c2 != '00'）"""
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


def load_counties(zf, base_path: str) -> dict[tuple[str, str], str]:
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
        if dept == "000" and li == "0000" and c2 == "00" and name and name != "全國":
            out[(c0, c1)] = name
    return out


def load_candidates(zf, cand_path: str):
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


def load_totals(zf, ctks_path: str):
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
        elected = 1 if row[9].strip() == "*" else 0
        out[(c0, c1, c2, cand_num)] = (votes, elected)
    return out


def format_district(c0, c1, c2, counties, sub_names):
    sub = sub_names.get((c0, c1, c2))
    if sub:
        return sub
    county = counties.get((c0, c1))
    return county or f"地區({c0}, {c1}, {c2})"


JOBS = [
    # (election_id, year_key, [scope_keywords])
    (22, "20101127", ["區域議員"]),   # 2010 五都區域議員
    (31, "2014-103", ["區域議員"]),   # 2014 含直轄市 + 縣市
    (40, "2018-107", ["區域議員"]),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    with zipfile.ZipFile(ZIP_PATH) as zf:
        for election_id, year_key, scopes in JOBS:
            print(f"\n=== election_id={election_id} {year_key} ===")
            counties = {}
            sub_names = {}
            cands = {}
            totals = {}
            scope_substrs = scopes + ["區域議員"]
            # 收集所有「直轄市區域議員」與「縣市區域議員」的 elcand/elbase/elctks
            for scope in scope_substrs:
                for sub_dir in ["直轄市區域議員", "縣市區域議員", "區域議員"]:
                    if sub_dir != scope and scope not in sub_dir:
                        continue
                    base = find_path(zf, year_key, sub_dir, suffix="/elbase.csv")
                    cand = find_path(zf, year_key, sub_dir, suffix="/elcand.csv")
                    ctks = find_path(zf, year_key, sub_dir, suffix="/elctks.csv")
                    if base and cand and ctks:
                        counties.update(load_counties(zf, base))
                        sub_names.update(load_district_names(zf, base))
                        cands.update(load_candidates(zf, cand))
                        totals.update(load_totals(zf, ctks))
            print(f"  {len(counties)} 縣市 / {len(sub_names)} 選區 / {len(cands)} 候選人 / {len(totals)} 票")

            updated = unmatched = 0
            for (c0, c1, c2, cn), (votes, elected) in totals.items():
                name = cands.get((c0, c1, c2, cn))
                if not name:
                    unmatched += 1
                    continue
                district = format_district(c0, c1, c2, counties, sub_names)
                row = conn.execute(
                    "SELECT candidate_id FROM candidates WHERE election_id=? AND name=?",
                    (election_id, name),
                ).fetchone()
                if not row:
                    unmatched += 1
                    continue
                cid = row["candidate_id"]
                # 嘗試 UPDATE existing row（無論 district 是什麼）
                ex = conn.execute(
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
                        updated += 1
                    except sqlite3.IntegrityError:
                        unmatched += 1
            conn.commit()
            print(f"  ✓ 更新/新增 {updated}，未對應 {unmatched}")

    conn.close()
    print("\n完成")


if __name__ == "__main__":
    main()
