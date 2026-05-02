"""
從 data/votedata.zip 的結構化 CSV 匯入選舉資料。

比 parse_and_import.py（Excel 版）更完整：
  - 政黨對應（elpaty.csv → parties 表）
  - 當選旗標（elcand.csv col 14='*'）
  - 縣市層級得票數（elctks.csv + elbase.csv）

支援選舉類型：
  - 總統     → presidential
  - 區域/山地/平地立委 → legislative
  - 不分區政黨  → legislative（政黨票，候選人為政黨名稱）
  - C1/*     → mayoral（縣市長）
  - R1-R3    → council（議員，multi-member SNTV，不計算當選旗標）

用法：
  python scripts/import_votedata.py
  python scripts/import_votedata.py --year 2024
  python scripts/import_votedata.py --dry-run
"""

import argparse
import io
import json
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
ZIP_PATH = ROOT / "data" / "votedata.zip"
INDEX_PATH = ROOT / "data" / "elections_index.json"
DB_PATH = ROOT / "data" / "db.sqlite"


# ── 分類規則：從資料夾路徑判斷選舉類型 ───────────────────────────────────────

# (leaf_folder, parent_folder) → (election_type, description)
CLASSIFY_RULES: list[tuple[str, str, str, str | None]] = [
    # leaf        parent    type            description
    ("總統",       "",       "presidential", None),
    ("區域立委",   "",       "legislative",  "區域"),
    ("不分區政黨", "",       "legislative",  "不分區政黨"),
    ("山地立委",   "",       "legislative",  "山地原住民"),
    ("平地立委",   "",       "legislative",  "平地原住民"),
    # 2024 前舊版命名
    ("區域",       "立委",   "legislative",  "區域"),
    ("山原",       "立委",   "legislative",  "山地原住民"),
    ("平原",       "立委",   "legislative",  "平地原住民"),
    # 縣市長（含直轄市長 city 和省轄縣市 prv）
    ("city",       "C1",     "mayoral",      None),
    ("prv",        "C1",     "mayoral",      None),
    # 議員（R1=直轄市議員區域, R2=直轄市原住民, R3=省轄議員）
    ("city",       "R1",     "council",      "區域"),
    ("prv",        "R1",     "council",      "區域"),
    ("city",       "R2",     "council",      "平地原住民"),
    ("prv",        "R2",     "council",      "平地原住民"),
    ("city",       "R3",     "council",      "山地原住民"),
    ("prv",        "R3",     "council",      "山地原住民"),
    # 早期直接用中文命名
    ("縣市長",         "",     "mayoral",  None),
    ("直轄市長",       "",     "mayoral",  None),
    # 2018 格式（直接用中文選別名稱）
    ("直轄市市長",     "",     "mayoral",  None),
    ("縣市市長",       "",     "mayoral",  None),
    ("直轄市區域議員", "",     "council",  "區域"),
    ("縣市區域議員",   "",     "council",  "區域"),
    ("直轄市平原議員", "",     "council",  "平地原住民"),
    ("縣市平原議員",   "",     "council",  "平地原住民"),
    ("直轄市山原議員", "",     "council",  "山地原住民"),
    ("縣市山原議員",   "",     "council",  "山地原住民"),
]

# 年份無法從路徑推斷時的手動對照表
MANUAL_YEAR_MAP: dict[str, int] = {
    "9任總統":  1996,
    "3屆立委":  1995,
    "4屆立委":  1998,
    "5屆立委":  2001,
}

SUBJECT_ID_MAP = {
    "presidential": "P0",
    "legislative":  "L0",
    "mayoral":      "C2",
    "council":      "T1",
}


def _int(val, default: int = 0) -> int:
    """寬鬆 int 轉換，處理 '1 或空值等異常格式"""
    try:
        return int(str(val).lstrip("'").strip())
    except (ValueError, TypeError):
        return default


def classify(leaf: str, parent: str) -> tuple[str, str | None] | None:
    for rule_leaf, rule_parent, etype, edesc in CLASSIFY_RULES:
        if rule_leaf in leaf:
            if not rule_parent or rule_parent in parent:
                return etype, edesc
    return None


def extract_year(path: str) -> int | None:
    # 先嘗試手動對照
    for key, year in MANUAL_YEAR_MAP.items():
        if key in path:
            return year
    m = re.search(r"(19|20)(\d{2})", path)
    return int(m.group()) if m else None


# ── 資料庫 helpers ──────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def upsert_party(conn: sqlite3.Connection, name: str, abbr: str = "", color: str = "#888888") -> int:
    row = conn.execute("SELECT party_id FROM parties WHERE name = ?", (name,)).fetchone()
    if row:
        return row["party_id"]
    cur = conn.execute(
        "INSERT INTO parties (name, abbreviation, color_hex) VALUES (?, ?, ?)",
        (name, abbr or name[:3], color)
    )
    conn.commit()
    return cur.lastrowid


def upsert_election(conn: sqlite3.Connection, name: str, etype: str, date: str,
                    description: str | None, theme_id: str | None) -> int:
    if theme_id:
        row = conn.execute("SELECT election_id FROM elections WHERE theme_id = ?", (theme_id,)).fetchone()
        if row:
            return row["election_id"]
    # fallback: match by name + description（不同子類型要分開）
    if description is not None:
        row = conn.execute(
            "SELECT election_id FROM elections WHERE name = ? AND type = ? AND description = ?",
            (name, etype, description)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT election_id FROM elections WHERE name = ? AND type = ? AND description IS NULL",
            (name, etype)
        ).fetchone()
    if row:
        return row["election_id"]
    cur = conn.execute(
        "INSERT INTO elections (name, type, date, status, description, theme_id) VALUES (?, ?, ?, ?, ?, ?)",
        (name, etype, date, "completed", description, theme_id)
    )
    conn.commit()
    return cur.lastrowid


def upsert_candidate(conn: sqlite3.Connection, name: str, election_id: int,
                     party_id: int | None) -> int:
    row = conn.execute(
        "SELECT candidate_id FROM candidates WHERE name = ? AND election_id = ?",
        (name, election_id)
    ).fetchone()
    if row:
        if party_id is not None:
            conn.execute("UPDATE candidates SET party_id = ? WHERE candidate_id = ?",
                         (party_id, row["candidate_id"]))
        return row["candidate_id"]
    cur = conn.execute(
        "INSERT OR IGNORE INTO candidates (name, election_id, party_id) VALUES (?, ?, ?)",
        (name, election_id, party_id)
    )
    conn.commit()
    return cur.lastrowid or conn.execute(
        "SELECT candidate_id FROM candidates WHERE name = ? AND election_id = ?",
        (name, election_id)
    ).fetchone()["candidate_id"]


def upsert_result(conn: sqlite3.Connection, election_id: int, candidate_id: int,
                  district: str | None, votes: int, elected: bool):
    conn.execute(
        """INSERT INTO election_results (election_id, candidate_id, district, votes, elected)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(election_id, candidate_id, district)
           DO UPDATE SET votes=excluded.votes, elected=excluded.elected""",
        (election_id, candidate_id, district, votes, int(elected))
    )


# ── CSV 解析 ────────────────────────────────────────────────────────────────

def read_csv(z: zipfile.ZipFile, info: zipfile.ZipInfo) -> pd.DataFrame:
    data = z.read(info.filename)
    try:
        return pd.read_csv(io.BytesIO(data), header=None, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(io.BytesIO(data), header=None, encoding="big5")


def parse_parties(df: pd.DataFrame) -> dict[int, str]:
    """elpaty.csv: col0=代碼, col1=名稱"""
    result = {}
    for _, row in df.iterrows():
        try:
            code = int(row[0])
            name = str(row[1]).strip()
            result[code] = name
        except (ValueError, TypeError):
            pass
    return result


def parse_candidates(df: pd.DataFrame, is_presidential: bool) -> list[dict]:
    """
    elcand.csv 欄位：
      0-4  = 地區代碼（county, dist, sub-dist, ?, ?）
      5    = 候選人號次
      6    = 姓名
      7    = 政黨代碼
      8    = 正/副順序（總統：1=正, 2=副）
      13   = （其他旗標）
      14   = '*' 表示當選
    """
    if is_presidential:
        # 將正副搭檔合併為 "正/副"
        tickets: dict[tuple, list] = {}
        for _, row in df.iterrows():
            try:
                ticket_num = _int(row[5])
            except Exception:
                continue
            position = _int(row[8], default=1)
            area_key = (_int(row[0]), _int(row[1]), _int(row[2]))
            key = (area_key, ticket_num)
            tickets.setdefault(key, []).append({
                "position": position,
                "name": str(row[6]).strip(),
                "party_code": _int(row[7]),
                "elected": str(row[14]).strip() == "*" if len(row) > 14 else False,
            })
        candidates = []
        for (area_key, ticket_num), members in tickets.items():
            members.sort(key=lambda x: x["position"])
            name = "/".join(m["name"] for m in members)
            party_code = members[0]["party_code"]
            elected = members[0]["elected"]  # 正式候選人的旗標
            candidates.append({
                "area": area_key,
                "cand_num": ticket_num,
                "name": name,
                "party_code": party_code,
                "elected": elected,
            })
        return candidates
    else:
        result = []
        for _, row in df.iterrows():
            try:
                result.append({
                    "area": (_int(row[0]), _int(row[1]), _int(row[2])),
                    "cand_num": _int(row[5]),
                    "name": str(row[6]).strip(),
                    "party_code": _int(row[7]),
                    "elected": str(row[14]).strip() == "*" if len(row) > 14 else False,
                })
            except (ValueError, TypeError):
                pass
        return result


def parse_area_names(df_base: pd.DataFrame) -> dict[tuple, str]:
    """
    elbase.csv: col0=縣代碼, col1=次區域代碼, col2=選區代碼, col3=里鄰代碼, col4=投票所代碼, col5=名稱
    只取各層級的「合計」列（col4='0000'）作為地區名稱
    """
    names: dict[tuple, str] = {}
    for _, row in df_base.iterrows():
        if str(row[4]).strip() in ("0000", "00000", ""):
            try:
                key = (_int(row[0]), _int(row[1]), _int(row[2]))
                names[key] = str(row[5]).strip()
            except Exception:
                pass
    return names


def parse_votes(df_ctks: pd.DataFrame) -> dict[tuple, int]:
    """
    elctks.csv: col0=縣, col1=次區域, col2=選區, col3=里代, col4=投票所, col5=站號, col6=候選人號次, col7=票數
    回傳 {(county_code, dist_code, area_code, cand_num): votes}
    """
    totals: dict[tuple, int] = {}
    for _, row in df_ctks.iterrows():
        try:
            key = (_int(row[0]), _int(row[1]), _int(row[2]), _int(row[6]))
            totals[key] = totals.get(key, 0) + _int(row[7])
        except (ValueError, TypeError):
            pass
    return totals


# ── 主要流程 ──────────────────────────────────────────────────────────────────

def find_index_entry(index: list[dict], etype: str, description: str | None, year: int) -> dict | None:
    subject = SUBJECT_ID_MAP.get(etype)
    if not subject:
        return None
    pool = [e for e in index if e["subject_id"] == subject
            and (e.get("vote_date") or "").startswith(str(year))]
    # 日期由早到晚排序：複數選舉同年時，優先匹配主選舉（如 11/26 縣市長 > 12/18 嘉義補選）
    pool.sort(key=lambda e: e.get("vote_date", ""))
    if description:
        match = [e for e in pool if e.get("legislator_desc") == description]
        if match:
            return match[0]
    return pool[0] if pool else None


def process_folder(z: zipfile.ZipFile, leaf_dir: str,
                   etype: str, description: str | None, year: int,
                   index: list[dict], conn: sqlite3.Connection,
                   dry_run: bool) -> int:
    """
    處理單一選舉子資料夾，回傳匯入的 election_results 筆數
    """
    def get_file(name: str) -> pd.DataFrame | None:
        fname = leaf_dir + name
        for info in z.infolist():
            decoded = info.filename.encode("cp437").decode("cp950")
            if decoded == fname:
                return read_csv(z, info)
        return None

    df_cand = get_file("elcand.csv")
    df_party = get_file("elpaty.csv")
    df_ctks = get_file("elctks.csv")
    df_base = get_file("elbase.csv")

    if df_cand is None or df_party is None or df_ctks is None:
        print(f"    缺少必要檔案，跳過")
        return 0

    party_code_map = parse_parties(df_party)
    area_names: dict[tuple, str] = {}
    if df_base is not None:
        area_names = parse_area_names(df_base)

    is_presidential = (etype == "presidential")
    candidates = parse_candidates(df_cand, is_presidential)
    vote_totals = parse_votes(df_ctks)

    if not candidates:
        return 0

    # ── 找或建立 election ────────────────────────────────────────────────────
    idx_entry = find_index_entry(index, etype, description, year)
    election_name = idx_entry["name"] if idx_entry else f"{year}年選舉（{etype}）"
    election_date = idx_entry["vote_date"] if idx_entry else f"{year}-01-01"
    theme_id = idx_entry["theme_id"] if idx_entry else None

    if dry_run:
        elected_count = sum(1 for c in candidates if c["elected"])
        print(f"    [dry-run] {election_name} | {len(candidates)} 候選人 | 當選 {elected_count} 人")
        return 0

    election_id = upsert_election(conn, election_name, etype, election_date, description, theme_id)

    # ── 政黨 upsert ──────────────────────────────────────────────────────────
    party_id_map: dict[int, int | None] = {}
    for code, name in party_code_map.items():
        pid = upsert_party(conn, name)
        party_id_map[code] = pid

    # ── 候選人與選舉結果 ─────────────────────────────────────────────────────
    # 建立 (area, cand_num) → candidate_id 的對照
    cand_id_map: dict[tuple, int] = {}
    for c in candidates:
        pid = party_id_map.get(c["party_code"])
        cid = upsert_candidate(conn, c["name"], election_id, pid)
        cand_id_map[(c["area"], c["cand_num"])] = cid

        # 更新 elected 旗標（直接寫入 candidates 表的 elected 欄如果有的話）
        # 我們用 election_results 的 elected 欄記錄

    # ── 彙整得票（以縣市為單位）──────────────────────────────────────────────
    # 從 vote_totals 按 (county, dist, area, cand_num) 彙整成 (area_key, cand_num) → votes
    # 對總統選舉：area_key = (county, 0, 0)，即縣市層級
    # 對立委/縣市長：同上，取 (county, dist, 0) 作為選區識別

    # 先決定地區層級：找出在 area_names 中存在的最細 key
    county_votes: dict[tuple, dict[int, int]] = {}  # area_key → {cand_num: votes}
    for (c0, c1, c2, cand_num), votes in vote_totals.items():
        # 逐步降粗：優先用 (c0,c1,c2)，找不到就用 (c0,c1,0)，再找不到用 (c0,0,0)
        area_key = None
        for key in [(c0, c1, c2), (c0, c1, 0), (c0, 0, 0)]:
            if key in area_names:
                area_key = key
                break
        if area_key is None:
            area_key = (c0, 0, 0)

        county_votes.setdefault(area_key, {})
        county_votes[area_key][cand_num] = county_votes[area_key].get(cand_num, 0) + votes

    total_rows = 0
    elected_by_area: dict[tuple, int] = {}  # area_key → winning cand_num（SMD 適用）

    # council 選舉不設 elected 旗標（SNTV multi-member，需要更多資訊）
    compute_elected = etype != "council"

    # 找出每個地區的當選者（票數最多者，SMD 邏輯）
    if compute_elected:
        for area_key, cand_votes in county_votes.items():
            if not cand_votes:
                continue
            winner_cand_num = max(cand_votes, key=cand_votes.get)
            elected_by_area[area_key] = winner_cand_num

    # 但總統選舉應以全國總票數決定當選者，而非各縣市
    if etype == "presidential":
        national_totals: dict[int, int] = {}
        for area_key, cand_votes in county_votes.items():
            for cn, v in cand_votes.items():
                national_totals[cn] = national_totals.get(cn, 0) + v
        winner_cand_num = max(national_totals, key=national_totals.get) if national_totals else -1
        # 改寫 elected_by_area：所有地區的當選者都是全國得票最高者
        for area_key in county_votes:
            elected_by_area[area_key] = winner_cand_num

        # 同時尊重 elcand 的 elected 旗標（比計算更可靠）
        elected_cand_nums = {c["cand_num"] for c in candidates if c["elected"]}
        if elected_cand_nums:
            for area_key in county_votes:
                # 用 elcand 旗標覆蓋
                for cn in elected_cand_nums:
                    elected_by_area[area_key] = cn
                break  # 同一個人，不需要再迭代

    # 對立委 SMD 選舉，使用 elcand 的 elected 旗標（比縣市層級聚合更可靠）
    if etype == "legislative" and description in ("區域", "山地原住民", "平地原住民"):
        # 找出每個地區（立委選區）的當選者
        elected_by_cand_area: dict[tuple, bool] = {
            (c["area"], c["cand_num"]): c["elected"] for c in candidates
        }
        # 重建 elected_by_area：對每個 area_key，找當選的候選人
        elected_by_area = {}
        for (area, cn), is_elected in elected_by_cand_area.items():
            if is_elected:
                # area 是 (c0, c1, c2)，對應到 county_votes 的 area_key 需要匹配
                # 找最接近的 area_key
                for key in [area, (area[0], area[1], 0), (area[0], 0, 0)]:
                    if key in county_votes:
                        elected_by_area[key] = cn
                        break

    for area_key, cand_votes in county_votes.items():
        district = area_names.get(area_key, f"地區{area_key}")
        winner = elected_by_area.get(area_key, -1)

        for cand_num, votes in cand_votes.items():
            cid = None
            # 嘗試從 cand_id_map 找 candidate_id
            for c in candidates:
                # 對應 area：先精確，再放寬到縣市層級
                c_area = c["area"]
                area_match = (
                    c_area == area_key or
                    (c_area[0], c_area[1], 0) == area_key or
                    (c_area[0], 0, 0) == area_key or
                    (0, 0, 0) == area_key  # 全國
                )
                if area_match and c["cand_num"] == cand_num:
                    cid = cand_id_map.get((c["area"], cand_num))
                    break

            if cid is None:
                continue

            is_elected = compute_elected and (cand_num == winner)
            upsert_result(conn, election_id, cid, district, votes, is_elected)
            total_rows += 1

    conn.commit()
    return total_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, help="只匯入特定年份")
    parser.add_argument("--dry-run", action="store_true", help="只顯示，不寫入")
    args = parser.parse_args()

    if not ZIP_PATH.exists():
        print(f"找不到 {ZIP_PATH}", file=sys.stderr)
        sys.exit(1)

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8")) if INDEX_PATH.exists() else []
    conn = get_conn() if not args.dry_run else None

    # ── 掃描所有含 elcand.csv 的資料夾 ──────────────────────────────────────
    with zipfile.ZipFile(ZIP_PATH) as z:
        # 解碼檔名
        all_files: list[tuple[str, zipfile.ZipInfo]] = []
        for info in z.infolist():
            try:
                decoded = info.filename.encode("cp437").decode("cp950")
            except (UnicodeDecodeError, UnicodeEncodeError):
                decoded = info.filename
            all_files.append((decoded, info))

        # 找出所有含 elcand.csv 的資料夾
        leaf_dirs: set[str] = set()
        for decoded, _ in all_files:
            if decoded.endswith("elcand.csv"):
                leaf_dirs.add(decoded[: decoded.rfind("/") + 1])

        total_results = 0

        for leaf_dir in sorted(leaf_dirs):
            parts = leaf_dir.rstrip("/").split("/")
            leaf = parts[-1]      # 最後層：e.g. '總統', 'city', 'prv'
            parent = parts[-2] if len(parts) > 1 else ""  # 倒數第二：e.g. 'C1', '2024總統立委'

            classified = classify(leaf, parent)
            if classified is None:
                continue

            etype, description = classified
            year = extract_year("/".join(parts))

            if year is None:
                continue
            if args.year and year != args.year:
                continue

            # 跳過不在 elections_index 且不重要的選舉類型
            # （如鄉鎮市長、村里長等）
            if etype not in SUBJECT_ID_MAP:
                continue

            election_label = f"{year} {etype}" + (f"/{description}" if description else "")
            print(f"\n[{election_label}]  {leaf_dir}")

            n = process_folder(z, leaf_dir, etype, description, year,
                               index, conn, args.dry_run)
            if n:
                print(f"  → {n} 筆 election_results")
            total_results += n

    if conn:
        conn.close()
    tag = "[dry-run] " if args.dry_run else ""
    print(f"\n{tag}完成！共匯入 {total_results} 筆 election_results")


if __name__ == "__main__":
    main()
