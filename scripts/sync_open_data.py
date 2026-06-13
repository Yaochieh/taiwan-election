"""
開放資料同步框架（demo）

目的：定義一個可擴充的「來源 → 指標」對應，讓未來能用排程定期把
政府開放資料抓進政見追蹤系統，自動標註權威度。

使用情境：
  - 每月跑 `python scripts/sync_open_data.py --source taipei_social_housing`
  - 從 data.taipei 或內政部 API 拉最新數字
  - 自動寫入對應 target 的 progress 點，authority_level = 1（官方）

目前狀態：
  - 框架已就緒
  - 各 source 的 fetch 邏輯為 stub（需要研究實際 API 後填入）
  - 仍可作為 admin 手動執行的 helper

支援的指標範例（待實作）：
  - taipei_social_housing      臺北市社會住宅完工/開工/規劃戶數
  - taipei_urban_renewal       臺北市公辦都更案件數
  - taipei_long_term_care      臺北市長照床位
  - national_social_housing    全國社會住宅統計

執行：
  python scripts/sync_open_data.py --list                          # 列出來源
  python scripts/sync_open_data.py --source taipei_social_housing  # 跑特定來源
  python scripts/sync_open_data.py --all                           # 全跑
"""
import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Callable, NamedTuple

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"


class TargetMatch(NamedTuple):
    """資料源回傳一筆觀測值，要對應到哪個 target。"""
    person_name: str
    target_title_contains: str    # 用 title LIKE 找
    recorded_at: str               # YYYY-MM-DD
    current_value: float
    note: str
    source_url: str
    publisher: str
    authority_level: int = 1       # 官方=1


class Source(NamedTuple):
    key: str
    label: str
    fetcher: Callable[[], list[TargetMatch]]


# ─────────────────────────────────────────────────────────────
# 各 source 的 fetcher（目前為 stub）
# ─────────────────────────────────────────────────────────────

def fetch_taipei_social_housing() -> list[TargetMatch]:
    """從 data.taipei 拉臺北市社會住宅統計。

    目標 API（待研究）：
      - https://data.taipei/api/v1/dataset/{dataset_id}?scope=resourceAquire
      - 都發局 https://udd.gov.taipei

    待實作步驟：
      1. 找到「社會住宅興辦進度」資料集 ID
      2. 解析 dataset 的 resources 取得 CSV/JSON URL
      3. 解析每月/每季的累計數字
      4. 對應到「社會住宅興辦（任內 1.5 萬戶）」的子目標
    """
    print("  ⚠️  taipei_social_housing：API endpoint 待研究填入")
    return []


def fetch_taipei_urban_renewal() -> list[TargetMatch]:
    """從都更處拉公辦都更案件數。

    目標：https://uro.gov.taipei
    """
    print("  ⚠️  taipei_urban_renewal：API endpoint 待研究填入")
    return []


def fetch_taipei_long_term_care() -> list[TargetMatch]:
    """從衛生局/聯醫拉長照床位統計。"""
    print("  ⚠️  taipei_long_term_care：API endpoint 待研究填入")
    return []


def fetch_national_social_housing() -> list[TargetMatch]:
    """從內政部營建署或國家住都中心拉全國社宅統計。

    目標：https://pip.moi.gov.tw 或 https://www.hurc.org.tw
    """
    print("  ⚠️  national_social_housing：API endpoint 待研究填入")
    return []


SOURCES = [
    Source("taipei_social_housing", "臺北市社會住宅興辦進度", fetch_taipei_social_housing),
    Source("taipei_urban_renewal", "臺北市公辦都更案件", fetch_taipei_urban_renewal),
    Source("taipei_long_term_care", "臺北市長照床位", fetch_taipei_long_term_care),
    Source("national_social_housing", "全國社會住宅統計", fetch_national_social_housing),
]


# ─────────────────────────────────────────────────────────────
# 共用：把觀測值寫入 DB
# ─────────────────────────────────────────────────────────────

def apply_matches(matches: list[TargetMatch], dry_run: bool = False):
    if not matches:
        return
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    inserted = 0
    skipped = 0

    for m in matches:
        # 找目標
        target_rows = conn.execute("""
            SELECT target_id FROM platform_targets
            WHERE person_name = ? AND title LIKE ?
            ORDER BY target_id LIMIT 1
        """, (m.person_name, f"%{m.target_title_contains}%")).fetchall()
        if not target_rows:
            print(f"    ✗ 找不到目標：{m.person_name} / {m.target_title_contains}")
            skipped += 1
            continue
        target_id = target_rows[0]["target_id"]

        # 是否已有同日資料
        exists = conn.execute("""
            SELECT progress_id FROM platform_target_progress
            WHERE target_id = ? AND recorded_at = ?
        """, (target_id, m.recorded_at)).fetchone()
        if exists:
            print(f"    · {m.recorded_at} 已存在，跳過")
            skipped += 1
            continue

        if dry_run:
            print(f"    [dry] {m.target_title_contains} @ {m.recorded_at} = {m.current_value}")
            continue

        cur = conn.execute("""
            INSERT INTO platform_target_progress (target_id, recorded_at, current_value, note)
            VALUES (?, ?, ?, ?)
        """, (target_id, m.recorded_at, m.current_value, m.note))
        progress_id = cur.lastrowid
        conn.execute("""
            INSERT INTO platform_progress_sources
                (progress_id, url, source_type, publisher, authority_level)
            VALUES (?, ?, 'gov_open_data', ?, ?)
        """, (progress_id, m.source_url, m.publisher, m.authority_level))
        inserted += 1

    conn.commit()
    conn.close()
    print(f"  → 新增 {inserted} 筆，略過 {skipped} 筆")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.list:
        print("可用 source：")
        for s in SOURCES:
            print(f"  · {s.key}：{s.label}")
        return

    targets = [s for s in SOURCES if args.all or s.key == args.source]
    if not targets:
        ap.error("請用 --source <key> 或 --all 或 --list")

    for s in targets:
        print(f"\n=== {s.label} ===")
        matches = s.fetcher()
        apply_matches(matches, dry_run=args.dry_run)

    print("\n✓ 同步完成")


if __name__ == "__main__":
    main()
