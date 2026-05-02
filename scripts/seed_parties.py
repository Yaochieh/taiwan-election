"""
植入主要政黨基本資料到 parties 表。
用法：python scripts/seed_parties.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "db.sqlite"

PARTIES = [
    # (name, abbreviation, color_hex)
    ("民主進步黨", "民進黨", "#1B9431"),
    ("中國國民黨", "國民黨", "#000095"),
    ("台灣民眾黨", "民眾黨", "#28C8C8"),
    ("時代力量",   "時力",   "#FBBE01"),
    ("台灣基進",   "基進",   "#A73F24"),
    ("親民黨",     "親民黨", "#FF6310"),
    ("台灣團結聯盟","台聯",  "#B5CF3F"),
    ("新黨",       "新黨",   "#FEF101"),
    ("無黨籍",     "無黨籍", "#888888"),
]


def main():
    conn = sqlite3.connect(DB_PATH)
    inserted = 0
    for name, abbr, color in PARTIES:
        cur = conn.execute(
            "INSERT OR IGNORE INTO parties (name, abbreviation, color_hex) VALUES (?, ?, ?)",
            (name, abbr, color),
        )
        if cur.rowcount:
            inserted += 1
            print(f"  + {name}")
        else:
            print(f"  = {name} (已存在)")
    conn.commit()
    conn.close()
    print(f"\n完成，新增 {inserted} 筆政黨資料")


if __name__ == "__main__":
    main()
