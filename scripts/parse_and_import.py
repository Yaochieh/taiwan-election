"""
解析 data/downloads/ 下的 Excel ZIP 檔，匯入 SQLite。

用法：
  python scripts/parse_and_import.py               # 解析全部
  python scripts/parse_and_import.py --subject P0  # 只解析總統
  python scripts/parse_and_import.py --theme-id 4d83db17...
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
DOWNLOAD_DIR = ROOT / "data" / "downloads"
INDEX_PATH = ROOT / "data" / "elections_index.json"
DB_PATH = ROOT / "data" / "db.sqlite"

# 只處理 A05-1（全國）和 A05-2（縣市），跳過 A05-4（投開票所）
ALLOWED_LEVELS = {"A05-1", "A05-2"}


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS elections (
            election_id INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            type        TEXT NOT NULL,
            date        DATE NOT NULL,
            status      TEXT NOT NULL,
            description TEXT,
            theme_id    TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS parties (
            party_id     INTEGER PRIMARY KEY,
            name         TEXT NOT NULL,
            abbreviation TEXT NOT NULL,
            color_hex    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS candidates (
            candidate_id INTEGER PRIMARY KEY,
            name         TEXT NOT NULL,
            party_id     INTEGER REFERENCES parties(party_id),
            election_id  INTEGER REFERENCES elections(election_id),
            district     TEXT,
            background   TEXT,
            platform     TEXT,
            UNIQUE(name, election_id)
        );
        CREATE TABLE IF NOT EXISTS seats (
            seat_id     INTEGER PRIMARY KEY,
            election_id INTEGER REFERENCES elections(election_id),
            party_id    INTEGER REFERENCES parties(party_id),
            level       TEXT NOT NULL,
            count       INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS election_results (
            result_id    INTEGER PRIMARY KEY,
            election_id  INTEGER REFERENCES elections(election_id),
            candidate_id INTEGER REFERENCES candidates(candidate_id),
            district     TEXT,
            votes        INTEGER NOT NULL,
            elected      BOOLEAN NOT NULL DEFAULT 0,
            UNIQUE(election_id, candidate_id, district)
        );
    """)
    conn.commit()


def upsert_election(conn: sqlite3.Connection, entry: dict) -> int:
    row = conn.execute(
        "SELECT election_id FROM elections WHERE theme_id = ?", (entry["theme_id"],)
    ).fetchone()
    if row:
        return row["election_id"]
    subject_type_map = {
        "P0": "presidential", "L0": "legislative",
        "C2": "mayoral", "T1": "council",
    }
    cur = conn.execute(
        "INSERT OR IGNORE INTO elections (name, type, date, status, description, theme_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            entry["name"],
            subject_type_map.get(entry["subject_id"], "other"),
            entry["vote_date"],
            "completed",
            entry.get("legislator_desc"),
            entry["theme_id"],
        ),
    )
    conn.commit()
    return cur.lastrowid


def upsert_candidate(conn: sqlite3.Connection, name: str, election_id: int) -> int:
    row = conn.execute(
        "SELECT candidate_id FROM candidates WHERE name = ? AND election_id = ?",
        (name, election_id),
    ).fetchone()
    if row:
        return row["candidate_id"]
    cur = conn.execute(
        "INSERT OR IGNORE INTO candidates (name, election_id) VALUES (?, ?)",
        (name, election_id),
    )
    conn.commit()
    return cur.lastrowid


def insert_result(conn: sqlite3.Connection, election_id: int, candidate_id: int,
                  district: str, votes: int):
    conn.execute(
        "INSERT OR IGNORE INTO election_results "
        "(election_id, candidate_id, district, votes, elected) VALUES (?, ?, ?, ?, 0)",
        (election_id, candidate_id, district, votes),
    )


# ── Excel parsing ─────────────────────────────────────────────────────────────

def clean_text(val) -> str:
    if pd.isna(val):
        return ""
    return str(val).replace("　", "").strip()


def parse_candidates_from_row2(df: pd.DataFrame) -> list[str]:
    """
    Row 2 格式：(1)\n柯文哲\n吳欣盈  → "柯文哲/吳欣盈"
    回傳候選人名稱列表，順序對應欄位 1, 2, 3, ...
    """
    candidates = []
    row = df.iloc[2]
    for val in row[1:]:
        if pd.isna(val):
            break
        text = str(val).strip()
        # 移除 (N)\n 前綴
        text = re.sub(r"^\(\d+\)\n?", "", text)
        # 換行轉斜線（正副搭檔）
        names = [n.strip() for n in text.split("\n") if n.strip()]
        if not names:
            break
        candidates.append("/".join(names))
    return candidates


def detect_level(filename: str) -> str | None:
    """從檔名抽出 A05-1 / A05-2 等層級代碼"""
    m = re.search(r"(A\d{2}-\d+)", filename)
    return m.group(1) if m else None


def parse_excel_sheet(data: bytes, filename: str) -> tuple[list[str], list[tuple]]:
    """
    解析單一 Excel 檔案。
    回傳 (candidates, rows)
    rows 每筆為 (district, candidate_name, votes)
    """
    df = pd.read_excel(io.BytesIO(data), header=None)

    candidates = parse_candidates_from_row2(df)
    if not candidates:
        return [], []

    num_candidates = len(candidates)
    rows = []

    # 資料從第 5 列（index 5）開始
    for _, row in df.iloc[5:].iterrows():
        district = clean_text(row.iloc[0])
        if not district:
            continue
        for i, cand in enumerate(candidates):
            col_idx = i + 1
            if col_idx >= len(row):
                continue
            val = row.iloc[col_idx]
            if pd.isna(val):
                continue
            try:
                votes = int(val)
            except (ValueError, TypeError):
                continue
            rows.append((district, cand, votes))

    return candidates, rows


def decode_zip_filename(info: zipfile.ZipInfo) -> str:
    """ZIP 內中文檔名通常是 cp950 encoded 但被當 cp437 存入"""
    try:
        return info.filename.encode("cp437").decode("cp950")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return info.filename


# ── main ──────────────────────────────────────────────────────────────────────

def load_index() -> dict[str, dict]:
    if not INDEX_PATH.exists():
        print(f"找不到 {INDEX_PATH}，請先執行 build_elections_index.py", file=sys.stderr)
        sys.exit(1)
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {e["theme_id"]: e for e in data}


def process_zip(zip_path: Path, entry: dict, conn: sqlite3.Connection) -> int:
    """處理單一 ZIP，回傳匯入的結果筆數"""
    election_id = upsert_election(conn, entry)
    total = 0

    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            fname = decode_zip_filename(info)
            level = detect_level(fname)
            if level not in ALLOWED_LEVELS:
                continue
            if not fname.lower().endswith(".xlsx"):
                continue

            data = z.read(info.filename)
            try:
                candidates, rows = parse_excel_sheet(data, fname)
            except Exception as e:
                print(f"    解析失敗 {fname}: {e}")
                continue

            if not rows:
                continue

            # 確保所有候選人都已建立
            cand_ids = {
                name: upsert_candidate(conn, name, election_id)
                for name in candidates
            }

            for district, cand_name, votes in rows:
                cid = cand_ids.get(cand_name)
                if cid:
                    insert_result(conn, election_id, cid, district, votes)
                    total += 1

            conn.commit()
            print(f"    [{level}] {Path(fname).name}: {len(rows)} 筆")

    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", help="逗號分隔的 subject_id，例如 P0,L0")
    parser.add_argument("--theme-id", help="指定單一 theme_id")
    args = parser.parse_args()

    subject_filter = set(args.subject.split(",")) if args.subject else set()
    theme_filter = {args.theme_id} if args.theme_id else set()

    index = load_index()
    conn = get_conn()
    init_db(conn)

    zip_files = list(DOWNLOAD_DIR.rglob("*.zip"))
    if not zip_files:
        print(f"data/downloads/ 下找不到任何 ZIP 檔，請先執行 download_excel.py")
        sys.exit(1)

    total_results = 0
    for zip_path in sorted(zip_files):
        # 從路徑結構 downloads/{type_id}/{subject_id}/{theme_id}/xxx.zip 取得 theme_id
        parts = zip_path.parts
        try:
            dl_idx = next(i for i, p in enumerate(parts) if p == "downloads")
            theme_id = parts[dl_idx + 3]
            subject_id = parts[dl_idx + 2]
        except (StopIteration, IndexError):
            print(f"路徑結構不符，跳過: {zip_path}")
            continue

        if theme_filter and theme_id not in theme_filter:
            continue
        if subject_filter and subject_id not in subject_filter:
            continue

        entry = index.get(theme_id)
        if not entry:
            print(f"  index 中找不到 theme_id={theme_id[:8]}，跳過")
            continue

        print(f"\n[{entry['name']}] {zip_path.name}")
        n = process_zip(zip_path, entry, conn)
        total_results += n
        print(f"  小計: {n} 筆結果")

    conn.close()
    print(f"\n完成！共匯入 {total_results} 筆 election_results")


if __name__ == "__main__":
    main()
