"""匯入 2022（111 年）議員選舉結果。

import_votedata.py 的通用流程不適合 2022 議員：
  - 2022 中選會代碼 T1/T2/T3 = 議員（區域／平地原住民／山地原住民），底下 prv = 直轄市、city = 縣市；
    R1–R3 在 2022 是代表，不是議員（zip 內「選舉種類代碼.xlsx」）。
  - 通用流程以姓名建立候選人、以縣市層級彙整票數，複數選區會把同場同名不同人併成一人、
    選區變成「地區(63, 0, 0)」。

本腳本直接讀 elbase / elcand / elctks，候選人以 (姓名, 選舉, 選區) 區分，
得票取 elctks 的選區合計列，當選以 elcand 的「*」為準（中選會審定）。

分場方式比照 2026：
  - 直轄市（prv）：區域、平地原住民、山地原住民各一場（同 2018 的描述）
  - 縣市（city）：一場「縣市議員」，原住民選區併入（2026 縣市議員也是如此）

選區命名比照既有 2018 資料：「臺北市第01選區」；直轄市原住民選區用縣市名。

用法：
  python scripts/import_council_2022.py --dry-run
  python scripts/import_council_2022.py
"""
import argparse
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
ZIP_PATH = ROOT / "data" / "votedata.zip"
DB_PATH = ROOT / "data" / "db.sqlite"
DATE = "2022-11-26"
SOURCE = "中選會選舉資料庫 votedata.zip：2022-111年地方公職人員選舉/{code}/{level}"

# (代碼, 層級) → (選舉名稱, 描述, 原住民選區是否以縣市為名)
GROUPS = [
    ("T1", "prv", "111年直轄市議員選舉", "區域", False),
    ("T2", "prv", "111年直轄市議員選舉", "平地原住民", True),
    ("T3", "prv", "111年直轄市議員選舉", "山地原住民", True),
    ("T1", "city", "111年縣市議員選舉", "縣市議員", False),
    ("T2", "city", "111年縣市議員選舉", "縣市議員", False),
    ("T3", "city", "111年縣市議員選舉", "縣市議員", False),
]


def dec(n: str) -> str:
    try:
        return n.encode("cp437").decode("big5")
    except Exception:
        return n


def read(z: zipfile.ZipFile, code: str, level: str, fname: str) -> list[list[str]]:
    for n in z.namelist():
        d = dec(n)
        if "2022-111年地方公職人員選舉" in d and d.endswith(f"/{code}/{level}/{fname}"):
            text = z.read(n).decode("utf-8")
            return [[c.strip().strip("'").strip('"') for c in line.split(",")] for line in text.splitlines() if line]
    raise FileNotFoundError(f"{code}/{level}/{fname}")


def load_group(z, code, level, county_named):
    base = read(z, code, level, "elbase.csv")
    county = {(r[0], r[1]): r[5] for r in base if r[2] == "00" and r[3] == "000" and r[4] == "0000" and r[0] != "00"}
    party = {r[0]: r[1] for r in read(z, code, level, "elpaty.csv")}
    votes = {}
    for r in read(z, code, level, "elctks.csv"):
        # 選區合計列：鄉鎮（r[3]）、村里（r[4]）都是 0
        if r[2] != "00" and r[3] == "000" and r[4] == "0000":
            votes[(r[0], r[1], r[2], r[6])] = int(r[7])
    out = []
    for r in read(z, code, level, "elcand.csv"):
        key = (r[0], r[1], r[2])
        cty = county[(r[0], r[1])]
        district = cty if county_named else f"{cty}第{int(r[2]):02d}選區"
        out.append({
            "name": r[6],
            "party": party.get(r[7]),
            "district": district,
            "votes": votes.get(key + (r[5],)),
            "elected": r[14] == "*",
            "incumbent": r[13] == "Y",
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    z = zipfile.ZipFile(ZIP_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")

    for code, level, name, desc, county_named in GROUPS:
        rows = load_group(z, code, level, county_named)
        missing = [r["name"] for r in rows if r["votes"] is None]
        assert not missing, f"{code}/{level} 缺得票：{missing[:5]}"
        print(f"{code}/{level} → {name}／{desc}：{len(rows)} 人、當選 {sum(r['elected'] for r in rows)}、"
              f"選區 {len({r['district'] for r in rows})}")
        if args.dry_run:
            continue
        row = conn.execute("SELECT election_id FROM elections WHERE name=? AND type='council' AND description=?",
                           (name, desc)).fetchone()
        eid = row[0] if row else conn.execute(
            "INSERT INTO elections (name, type, date, status, description) VALUES (?, 'council', ?, 'completed', ?)",
            (name, DATE, desc)).lastrowid
        src = SOURCE.format(code=code, level=level)
        for r in rows:
            pid = None
            if r["party"]:
                p = conn.execute("SELECT party_id FROM parties WHERE name=?", (r["party"],)).fetchone()
                pid = p[0] if p else conn.execute("INSERT INTO parties (name) VALUES (?)", (r["party"],)).lastrowid
            conn.execute(
                "INSERT OR IGNORE INTO candidates (name, election_id, party_id, district, official_source) VALUES (?,?,?,?,?)",
                (r["name"], eid, pid, r["district"], src))
            cid = conn.execute("SELECT candidate_id FROM candidates WHERE name=? AND election_id=? AND district=?",
                               (r["name"], eid, r["district"])).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO election_results (election_id, candidate_id, district, votes, elected) VALUES (?,?,?,?,?)",
                (eid, cid, r["district"], r["votes"], int(r["elected"])))
    if not args.dry_run:
        conn.commit()
    print("完成" + ("（dry-run）" if args.dry_run else ""))


if __name__ == "__main__":
    main()
