"""匯入議員選舉結果（2014／2018／2022），候選人以 (姓名, 選區) 區分。

import_votedata.py 的通用流程不適合議員（複數選區）：以姓名建立候選人會把同場同名不同人
併成一人，原住民選區也沒解析（出現「地區(…)」、臺東／花蓮／屏東原住民席次少算）。
本腳本直接讀 elbase / elcand / elctks：得票取 elctks 的選區合計列，當選以 elcand 的「*」為準。

資料夾：
  - 2022：T1/T2/T3（區域／平地／山地）底下 prv=直轄市、city=縣市；R1–R3 在 2022 是代表，不是議員
  - 2014／2018：直轄市區域議員、直轄市平原議員、直轄市山原議員、縣市區域議員、縣市平原議員、縣市山原議員

分場比照 2026：直轄市「區域／平地原住民／山地原住民」各一場（沿用既有 election_id，網址不變），
縣市一場「縣市議員」（原住民選區併入）。選區命名「臺北市第01選區」；直轄市原住民選區用縣市名。

重跑會先刪除目標選舉的 election_results 與 candidates 再寫入（這些選舉沒有其他表引用，
匯入前會檢查）。

用法：
  python scripts/import_council_results.py --year 2018 --dry-run
  python scripts/import_council_results.py --year 2018
"""
import argparse
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
ZIP_PATH = ROOT / "data" / "votedata.zip"
SOURCE = "中選會選舉資料庫 votedata.zip：{root}/{sub}"
DB_PATH = ROOT / "data" / "db.sqlite"

# 年份 → (zip 內根資料夾, 投票日, 民國年, [(子資料夾, 直轄市?, 描述, 原住民選區以縣市為名?)])
YEARS = {
    2022: ("2022-111年地方公職人員選舉", "2022-11-26", 111, [
        ("T1/prv", True, "區域", False), ("T2/prv", True, "平地原住民", True), ("T3/prv", True, "山地原住民", True),
        ("T1/city", False, "縣市議員", False), ("T2/city", False, "縣市議員", False), ("T3/city", False, "縣市議員", False)]),
    2018: ("2018-107年地方公職人員選舉", "2018-11-24", 107, [
        ("直轄市區域議員", True, "區域", False), ("直轄市平原議員", True, "平地原住民", True),
        ("直轄市山原議員", True, "山地原住民", True), ("縣市區域議員", False, "縣市議員", False),
        ("縣市平原議員", False, "縣市議員", False), ("縣市山原議員", False, "縣市議員", False)]),
    2014: ("2014-103年地方公職人員選舉", "2014-11-29", 103, [
        ("直轄市區域議員", True, "區域", False), ("直轄市平原議員", True, "平地原住民", True),
        ("直轄市山原議員", True, "山地原住民", True), ("縣市區域議員", False, "縣市議員", False),
        ("縣市平原議員", False, "縣市議員", False), ("縣市山原議員", False, "縣市議員", False)]),
}
# 既有直轄市議員選舉沿用 election_id（網址不變）：(年, 描述) → id
KEEP_IDS = {(2014, "區域"): 31, (2014, "山地原住民"): 32, (2014, "平地原住民"): 34,
            (2018, "區域"): 40, (2018, "山地原住民"): 41, (2018, "平地原住民"): 43}


def dec(n: str) -> str:
    try:
        return n.encode("cp437").decode("big5")
    except Exception:
        return n


def read(z: zipfile.ZipFile, root: str, sub: str, fname: str) -> list[list[str]]:
    for n in z.namelist():
        d = dec(n)
        if root in d and d.endswith(f"/{sub}/{fname}"):
            raw = z.read(n)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("big5")
            # 2014/2018 欄位是 "'63" 形式：先剝雙引號再剝單引號
            return [[c.strip().strip('"').strip("'") for c in line.split(",")] for line in text.splitlines() if line]
    raise FileNotFoundError(f"{root}/{sub}/{fname}")


def load_group(z, root, sub, county_named):
    base = read(z, root, sub, "elbase.csv")
    county = {(r[0], r[1]): r[5] for r in base if r[2] == "00" and r[3] == "000" and r[4] == "0000" and r[0] != "00"}
    party = {r[0]: r[1] for r in read(z, root, sub, "elpaty.csv")}
    votes = {}
    for r in read(z, root, sub, "elctks.csv"):
        # 選區合計列：鄉鎮（r[3]）、村里（r[4]）都是 0
        if r[2] != "00" and r[3] == "000" and r[4] == "0000":
            votes[(r[0], r[1], r[2], r[6])] = int(r[7])
    out = []
    for r in read(z, root, sub, "elcand.csv"):
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


def referencing_rows(conn, eids: list[int]) -> dict[str, int]:
    """除 candidates / election_results 外，還有哪些表引用這些選舉或其候選人（有就不能刪）。"""
    q = ",".join("?" * len(eids))
    out = {}
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if t in ("candidates", "election_results", "elections"):
            continue
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
        n = 0
        if "candidate_id" in cols:
            n += conn.execute(f"SELECT COUNT(*) FROM {t} WHERE candidate_id IN "
                              f"(SELECT candidate_id FROM candidates WHERE election_id IN ({q}))", eids).fetchone()[0]
        if "election_id" in cols:
            n += conn.execute(f"SELECT COUNT(*) FROM {t} WHERE election_id IN ({q})", eids).fetchone()[0]
        if n:
            out[t] = n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=sorted(YEARS))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    root, date, roc, groups = YEARS[args.year]
    z = zipfile.ZipFile(ZIP_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")

    loaded = []
    for sub, muni, desc, county_named in groups:
        rows = load_group(z, root, sub, county_named)
        missing = [r["name"] for r in rows if r["votes"] is None]
        assert not missing, f"{sub} 缺得票：{missing[:5]}"
        name = f"{roc}年{'直轄市' if muni else '縣市'}議員選舉"
        print(f"{sub} → {name}／{desc}：{len(rows)} 人、當選 {sum(r['elected'] for r in rows)}、"
              f"選區 {len({r['district'] for r in rows})}")
        loaded.append((sub, name, desc, rows))
    if args.dry_run:
        print("完成（dry-run）")
        return

    # 目標選舉：沿用的 id ＋ 同名同描述的既有選舉
    targets = {}
    for sub, name, desc, _ in loaded:
        eid = KEEP_IDS.get((args.year, desc)) if "直轄市" in name else None
        if eid is None:
            row = conn.execute("SELECT election_id FROM elections WHERE name=? AND type='council' AND description=?",
                               (name, desc)).fetchone()
            eid = row[0] if row else None
        if eid is None:
            eid = conn.execute(
                "INSERT INTO elections (name, type, date, status, description) VALUES (?, 'council', ?, 'completed', ?)",
                (name, date, desc)).lastrowid
        else:
            conn.execute("UPDATE elections SET name=?, date=? WHERE election_id=?", (name, date, eid))
        targets[(name, desc)] = eid
    eids = sorted(set(targets.values()))
    refs = referencing_rows(conn, eids)
    assert not refs, f"其他表引用這些選舉，不能重匯：{refs}"
    q = ",".join("?" * len(eids))
    conn.execute(f"DELETE FROM election_results WHERE election_id IN ({q})", eids)
    conn.execute(f"DELETE FROM candidates WHERE election_id IN ({q})", eids)

    for sub, name, desc, rows in loaded:
        eid = targets[(name, desc)]
        src = SOURCE.format(root=root, sub=sub)
        for r in rows:
            pid = None
            if r["party"]:
                p = conn.execute("SELECT party_id FROM parties WHERE name=?", (r["party"],)).fetchone()
                pid = p[0] if p else conn.execute("INSERT INTO parties (name) VALUES (?)", (r["party"],)).lastrowid
            cur = conn.execute(
                "INSERT INTO candidates (name, election_id, party_id, district, official_source) VALUES (?,?,?,?,?)",
                (r["name"], eid, pid, r["district"], src))
            conn.execute(
                "INSERT INTO election_results (election_id, candidate_id, district, votes, elected) VALUES (?,?,?,?,?)",
                (eid, cur.lastrowid, r["district"], r["votes"], int(r["elected"])))
    conn.commit()
    print(f"完成：選舉 {eids}")


if __name__ == "__main__":
    main()
