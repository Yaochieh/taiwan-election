"""
政見追蹤 v2 schema 升級：

  platform_targets 加：
    parent_target_id  INTEGER  支援父子層級（社宅總指標 → 規劃/開工/完工/入住）
    data_source_kind  TEXT     official_gov / news_only / mixed
    rank              INTEGER  顯示順序

  platform_progress_sources（新表）：
    source_id        INTEGER PK
    progress_id      INTEGER FK
    url              TEXT
    source_type      TEXT       gov_open_data / gov_announce / news / monitor / academic
    publisher        TEXT       例：內政部營建署、自由時報、苗博雅議員
    authority_level  INTEGER    1=最高 (政府開放資料) ... 5=最低 (個人部落格)
    retrieved_at     DATETIME

執行：
  python scripts/migrate_tracking_v2.py
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"


def add_col_if_missing(conn, table: str, col: str, decl: str):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        print(f"  ✓ {table}.{col} 已新增")
    else:
        print(f"  · {table}.{col} 已存在")


def main():
    conn = sqlite3.connect(DB_PATH)

    print("升級 platform_targets 欄位...")
    add_col_if_missing(conn, "platform_targets", "parent_target_id", "INTEGER REFERENCES platform_targets(target_id)")
    add_col_if_missing(conn, "platform_targets", "data_source_kind", "TEXT")
    add_col_if_missing(conn, "platform_targets", "rank", "INTEGER DEFAULT 0")

    print("\n建立 platform_progress_sources 表...")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS platform_progress_sources (
            source_id       INTEGER PRIMARY KEY,
            progress_id     INTEGER NOT NULL REFERENCES platform_target_progress(progress_id) ON DELETE CASCADE,
            url             TEXT,
            source_type     TEXT,
            publisher       TEXT,
            authority_level INTEGER,
            retrieved_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_pps_progress ON platform_progress_sources(progress_id);
    """)
    print("  ✓ platform_progress_sources 完成")

    conn.commit()
    conn.close()
    print("\n✓ v2 schema 升級完成")


if __name__ == "__main__":
    main()
