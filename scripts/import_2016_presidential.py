"""
從 CEC 2016 總統選舉 Excel 包匯入 per-county 與 per-township 資料。

來源：https://db.cec.gov.tw/.../61b4dda0ebac3332203ef3729a9a0ada/
      總統-各投票所得票明細及概況(Excel檔).zip

執行：
  python scripts/import_2016_presidential.py [--zip /tmp/pres2016.zip] [--dry-run]
"""
import argparse
import sqlite3
import urllib.request
import zipfile
from pathlib import Path

import xlrd

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"

THEME_ID = "61b4dda0ebac3332203ef3729a9a0ada"
DOWNLOAD_URL = (
    f"https://db.cec.gov.tw/static/elections/data/attachments/ELC/P0/"
    f"{THEME_ID}/總統-各投票所得票明細及概況(Excel檔).zip"
)

# 候選人號次（1=朱立倫, 2=蔡英文, 3=宋楚瑜）→ DB 中的姓名
# 副總統同票數會合併用，需找到 election_id 對應的 candidate_id
ELECTION_DATE = "2016-01-16"


def ensure_zip(path: Path) -> Path:
    if path.exists():
        return path
    print(f"下載 {DOWNLOAD_URL} → {path}")
    req = urllib.request.Request(
        DOWNLOAD_URL, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req) as resp, open(path, "wb") as f:
        f.write(resp.read())
    return path


def decoded_name(info: zipfile.ZipInfo) -> str:
    try:
        return info.filename.encode("cp437").decode("big5")
    except Exception:
        return info.filename


def parse_a05_1(wb_data: bytes) -> dict[str, dict[int, int]]:
    """A05-1：各縣市總票數。回傳 {county: {cand_num: votes}}。"""
    wb = xlrd.open_workbook(file_contents=wb_data)
    sh = wb.sheet_by_index(0)
    out = {}
    for row in range(6, sh.nrows):
        name = str(sh.cell_value(row, 0)).strip().replace("　", "")
        if not name or name == "總計":
            continue
        try:
            votes = {
                1: int(sh.cell_value(row, 1) or 0),
                2: int(sh.cell_value(row, 2) or 0),
                3: int(sh.cell_value(row, 3) or 0),
            }
        except (ValueError, TypeError):
            continue
        if all(v == 0 for v in votes.values()):
            continue
        out[name] = votes
    return out


def parse_a05_3(wb_data: bytes) -> dict[str, dict[int, int]]:
    """A05-3：某縣市內各鄉鎮市區得票。回傳 {township: {cand_num: votes}}。
    鄉鎮列 = col0 非空且 col1 為空（村里列則 col1 非空）。
    """
    wb = xlrd.open_workbook(file_contents=wb_data)
    sh = wb.sheet_by_index(0)
    out = {}
    for row in range(6, sh.nrows):
        col0 = str(sh.cell_value(row, 0)).strip().replace("　", "")
        col1 = str(sh.cell_value(row, 1)).strip().replace("　", "")
        if not col0 or col1:
            continue
        if col0 == "總計":
            continue
        try:
            votes = {
                1: int(sh.cell_value(row, 2) or 0),
                2: int(sh.cell_value(row, 3) or 0),
                3: int(sh.cell_value(row, 4) or 0),
            }
        except (ValueError, TypeError):
            continue
        if all(v == 0 for v in votes.values()):
            continue
        out[col0] = votes
    return out


def get_candidate_ids(conn: sqlite3.Connection, election_id: int) -> dict[int, list[int]]:
    """全國總票數排序 → 對應 cand_num → candidate_ids（正副配對）。
    號次 1=朱立倫, 2=蔡英文, 3=宋楚瑜（按 CEC 號次順序）。
    DB 中既有「全國」一筆，可用得票數排序對應。"""
    cur = conn.execute(
        "SELECT er.candidate_id, c.name, c.background, er.votes "
        "FROM election_results er "
        "JOIN candidates c ON er.candidate_id = c.candidate_id "
        "WHERE er.election_id = ? AND er.district = '全國' "
        "ORDER BY er.votes DESC",
        (election_id,),
    )
    rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    groups: list[list[dict]] = []
    cur_v = None
    for r in rows:
        if cur_v != r["votes"]:
            groups.append([])
            cur_v = r["votes"]
        groups[-1].append(r)
    # 2016 民眾總票：1=朱立倫(3,813,365), 2=蔡英文(6,894,744), 3=宋楚瑜(1,576,861)
    # 排序大→小：蔡 > 朱 > 宋 → groups[0]=蔡組, groups[1]=朱組, groups[2]=宋組
    NUM_BY_RANK = {0: 2, 1: 1, 2: 3}
    cand_map: dict[int, list[int]] = {}
    for i, grp in enumerate(groups):
        num = NUM_BY_RANK.get(i)
        if num is None:
            continue
        cand_map[num] = [g["candidate_id"] for g in grp]
    return cand_map


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--zip",
        default="/tmp/pres2016.zip",
        help="2016 CEC Excel zip 路徑（若不存在會下載）",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    zip_path = ensure_zip(Path(args.zip))

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    election = conn.execute(
        "SELECT election_id FROM elections WHERE type='presidential' AND date=?",
        (ELECTION_DATE,),
    ).fetchone()
    if not election:
        print("✗ DB 找不到 2016 總統 election")
        return
    election_id = election["election_id"]
    cand_map = get_candidate_ids(conn, election_id)
    print(f"election_id={election_id}")
    print(f"cand_num → candidate_ids: {cand_map}")

    with zipfile.ZipFile(zip_path) as zf:
        # 找 A05-1
        a05_1 = None
        a05_3_files: list[tuple[zipfile.ZipInfo, str]] = []
        for info in zf.infolist():
            name = decoded_name(info)
            if "A05-1" in name:
                a05_1 = info
            elif "A05-3" in name and name.endswith(".xls"):
                # 抽取縣市名（檔名最後括號）
                start = name.rfind("(")
                end = name.rfind(")")
                if start >= 0 and end > start:
                    county = name[start + 1 : end].strip()
                    a05_3_files.append((info, county))

        # ========= 縣市層級 =========
        if a05_1:
            print("\n=== A05-1：縣市層級 ===")
            with zf.open(a05_1) as fp:
                wb_data = fp.read()
            county_votes = parse_a05_1(wb_data)
            print(f"  解析 {len(county_votes)} 縣市")
            inserted = updated = 0
            for county, votes_by_num in county_votes.items():
                for num, total in votes_by_num.items():
                    for cid in cand_map.get(num, []):
                        if args.dry_run:
                            continue
                        ex = conn.execute(
                            "SELECT result_id, votes FROM election_results "
                            "WHERE election_id=? AND candidate_id=? AND district=?",
                            (election_id, cid, county),
                        ).fetchone()
                        if ex:
                            if ex["votes"] != total:
                                conn.execute(
                                    "UPDATE election_results SET votes=? WHERE result_id=?",
                                    (total, ex["result_id"]),
                                )
                                updated += 1
                        else:
                            conn.execute(
                                "INSERT INTO election_results "
                                "(election_id, candidate_id, district, votes, elected) "
                                "VALUES (?, ?, ?, ?, 0)",
                                (election_id, cid, county, total),
                            )
                            inserted += 1
            if not args.dry_run:
                conn.commit()
            print(f"  ✓ 新增 {inserted}、更新 {updated}")

        # ========= 鄉鎮層級 =========
        print(f"\n=== A05-3：鄉鎮層級（{len(a05_3_files)} 個縣市） ===")
        twn_inserted = twn_updated = 0
        for info, county in sorted(a05_3_files, key=lambda x: x[1]):
            with zf.open(info) as fp:
                wb_data = fp.read()
            twn_votes = parse_a05_3(wb_data)
            for township, votes_by_num in twn_votes.items():
                for num, total in votes_by_num.items():
                    for cid in cand_map.get(num, []):
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
                                twn_updated += 1
                        else:
                            conn.execute(
                                "INSERT INTO township_results "
                                "(election_id, candidate_id, county, township, votes) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (election_id, cid, county, township, total),
                            )
                            twn_inserted += 1
            print(f"  {county}: {len(twn_votes)} 鄉鎮")
        if not args.dry_run:
            conn.commit()
        print(f"\n總計：township 新增 {twn_inserted}、更新 {twn_updated}")

    conn.close()
    print("完成")


if __name__ == "__main__":
    main()
