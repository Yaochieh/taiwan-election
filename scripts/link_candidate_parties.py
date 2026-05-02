"""
將候選人與政黨對應，更新 candidates.party_id。

對應邏輯（優先順序）：
  1. 姓名完全符合 CANDIDATE_PARTY_MAP
  2. 姓名拆開後（斜線分隔的正副搭檔）任一人符合
  3. 候選人姓名包含政黨縮寫（例如「無黨籍」）

用法：
  python scripts/link_candidate_parties.py
  python scripts/link_candidate_parties.py --dry-run
"""

import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "db.sqlite"

# 候選人姓名 → 政黨名稱（依需要擴充）
CANDIDATE_PARTY_MAP: dict[str, str] = {
    # ── 2024 總統 ──────────────────────────────────────────────────────────────
    "賴清德":   "民主進步黨",
    "蕭美琴":   "民主進步黨",
    "侯友宜":   "中國國民黨",
    "趙少康":   "中國國民黨",
    "柯文哲":   "台灣民眾黨",
    "吳欣盈":   "台灣民眾黨",
    # ── 常見立委 / 縣市長（持續補充）──────────────────────────────────────────
    "韓國瑜":   "中國國民黨",
    "蔡英文":   "民主進步黨",
    "陳其邁":   "民主進步黨",
    "盧秀燕":   "中國國民黨",
    "黃國昌":   "台灣民眾黨",
    "陳椒華":   "時代力量",
    "王婉諭":   "時代力量",
    "陳柏惟":   "台灣基進",
}

# 候選人姓名關鍵字 → 政黨（補強：例如名稱中直接帶政黨字眼）
NAME_KEYWORD_PARTY: dict[str, str] = {
    "無黨籍": "無黨籍",
    "無黨團結聯盟": "無黨籍",
}


def build_party_lookup(conn: sqlite3.Connection) -> dict[str, int]:
    """party_name → party_id"""
    rows = conn.execute("SELECT party_id, name, abbreviation FROM parties").fetchall()
    lookup: dict[str, int] = {}
    for row in rows:
        lookup[row["name"]] = row["party_id"]
        lookup[row["abbreviation"]] = row["party_id"]
    return lookup


def resolve_party(candidate_name: str, party_lookup: dict[str, int]) -> int | None:
    """
    給定候選人姓名（可能含斜線如「賴清德/蕭美琴」），
    回傳對應的 party_id 或 None。
    """
    parts = [p.strip() for p in candidate_name.split("/")]

    # 1. 精確對應
    for part in parts:
        if part in CANDIDATE_PARTY_MAP:
            party_name = CANDIDATE_PARTY_MAP[part]
            pid = party_lookup.get(party_name)
            if pid:
                return pid

    # 2. 名稱關鍵字
    for keyword, party_name in NAME_KEYWORD_PARTY.items():
        if keyword in candidate_name:
            pid = party_lookup.get(party_name)
            if pid:
                return pid

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只顯示結果，不寫入 DB")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    party_lookup = build_party_lookup(conn)

    candidates = conn.execute(
        "SELECT candidate_id, name FROM candidates WHERE party_id IS NULL"
    ).fetchall()

    updated = skipped = 0
    for row in candidates:
        pid = resolve_party(row["name"], party_lookup)
        if pid is None:
            print(f"  ? 無法對應：{row['name']}")
            skipped += 1
            continue
        party_name = next(k for k, v in party_lookup.items() if v == pid and len(k) > 2)
        print(f"  ✓ {row['name']} → {party_name}")
        if not args.dry_run:
            conn.execute(
                "UPDATE candidates SET party_id = ? WHERE candidate_id = ?",
                (pid, row["candidate_id"]),
            )
        updated += 1

    if not args.dry_run:
        conn.commit()

    conn.close()
    tag = "[dry-run] " if args.dry_run else ""
    print(f"\n{tag}完成：對應 {updated} 筆，無法對應 {skipped} 筆")


if __name__ == "__main__":
    main()
