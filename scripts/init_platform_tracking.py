"""
政見追蹤系統 schema：

  platform_targets
    target_id          INTEGER PK
    person_name        TEXT     候選人姓名（同名聚合）
    election_id        INTEGER  關聯到當選那場選舉（用於 baseline 日期）
    category           TEXT     住宅 / 交通 / 教育 / 社福 / 經濟 / 環境
    title              TEXT     政見摘要（如：4 年興建 1.5 萬戶社會住宅）
    description        TEXT     完整描述
    metric_unit        TEXT     戶 / 公里 / 億元 / %
    baseline_value     REAL     政見提出時/上任時數值
    baseline_date      DATE     baseline 日期
    target_value       REAL     政見承諾達成值
    target_date        DATE     政見承諾期限
    status             TEXT     in_progress / achieved / failed / unknown
    source_url         TEXT     政見原文 URL
    created_at         DATETIME

  platform_target_progress
    progress_id        INTEGER PK
    target_id          INTEGER FK
    recorded_at        DATE
    current_value      REAL
    note               TEXT
    source_url         TEXT
    created_at         DATETIME

執行：
  python scripts/init_platform_tracking.py
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS platform_targets (
            target_id      INTEGER PRIMARY KEY,
            person_name    TEXT NOT NULL,
            election_id    INTEGER REFERENCES elections(election_id),
            category       TEXT,
            title          TEXT NOT NULL,
            description    TEXT,
            metric_unit    TEXT,
            baseline_value REAL,
            baseline_date  DATE,
            target_value   REAL,
            target_date    DATE,
            status         TEXT DEFAULT 'in_progress',
            source_url     TEXT,
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS platform_target_progress (
            progress_id   INTEGER PRIMARY KEY,
            target_id     INTEGER NOT NULL REFERENCES platform_targets(target_id) ON DELETE CASCADE,
            recorded_at   DATE NOT NULL,
            current_value REAL,
            note          TEXT,
            source_url    TEXT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_pt_person ON platform_targets(person_name);
        CREATE INDEX IF NOT EXISTS idx_ptp_target ON platform_target_progress(target_id);
    """)
    conn.commit()
    conn.close()
    print("✓ 政見追蹤 schema 初始化完成")


if __name__ == "__main__":
    main()
