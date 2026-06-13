"""
開放資料同步：把政府官方資料抓進政見追蹤系統（authority_level=1）。

支援的來源：
  taipei_social_housing      ✓ https://hms.udd.gov.taipei/api/BigData/project
  taipei_long_term_care      ✓ data.taipei CSV (立案住宿式長照機構)
  taipei_urban_renewal       ✗ 都更處未提供公開 API（stub）
  national_social_housing    ✗ 內政部營建署網站需爬蟲（stub）

執行：
  python scripts/sync_open_data.py --list                          # 列出來源
  python scripts/sync_open_data.py --source taipei_social_housing  # 跑特定
  python scripts/sync_open_data.py --all                           # 全跑
  python scripts/sync_open_data.py --all --dry-run                 # 試跑
"""
import argparse
import csv
import io
import json
import sqlite3
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Callable, NamedTuple

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db.sqlite"

USER_AGENT = "TaiwanElectionPlatform/1.0 (+github.com/Yaochieh/taiwan-election)"


class TargetMatch(NamedTuple):
    person_name: str
    target_title_contains: str
    recorded_at: str
    current_value: float
    note: str
    source_url: str
    publisher: str
    authority_level: int = 1


class Source(NamedTuple):
    key: str
    label: str
    fetcher: Callable[[], list[TargetMatch]]


# ─────────────────────────────────────────────────────────────
# 來源實作
# ─────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_taipei_social_housing() -> list[TargetMatch]:
    """臺北市社會住宅興辦進度 — 84 處建案、含戶數與階段。

    資料源：都市發展局 社會住宅興建工程戰情中心
    URL: https://hms.udd.gov.taipei/api/BigData/project
    更新頻率：每日
    """
    URL = "https://hms.udd.gov.taipei/api/BigData/project"
    PUBLISHER = "臺北市都市發展局（社宅戰情中心）"
    today = date.today().isoformat()

    try:
        raw = _http_get(URL)
        records = json.loads(raw)
    except Exception as e:
        print(f"  ✗ 抓取失敗：{e}")
        return []

    # 按 progress 分類加總戶數
    buckets: dict[str, int] = {}
    for r in records:
        progress = r.get("progress", "").strip()
        try:
            h = int(r.get("houseHolds", "0") or "0")
        except (TypeError, ValueError):
            h = 0
        buckets[progress] = buckets.get(progress, 0) + h

    # 對應到我們的子指標
    PROGRESS_TO_TARGET = {
        "已完工": ("已完工戶數", "完工"),
        "都更聯開分回": ("已完工戶數", "都更聯開分回（併入完工）"),
        "施工中及待開工": ("已開工戶數", "施工中及待開工"),
        "規劃中": ("規劃中戶數", "規劃中"),
        "招標中及待上網": ("規劃中戶數", "招標中及待上網（併入規劃）"),
    }

    # 累加（同一子指標的 buckets 加起來）
    target_totals: dict[str, list[str]] = {}
    for progress, (target_title, note_part) in PROGRESS_TO_TARGET.items():
        if progress in buckets:
            target_totals.setdefault(target_title, [])
            target_totals[target_title].append(
                (progress, buckets[progress])
            )

    matches: list[TargetMatch] = []
    for target_title, parts in target_totals.items():
        total = sum(v for _, v in parts)
        notes = "、".join(f"{p}: {v}" for p, v in parts)
        matches.append(TargetMatch(
            person_name="蔣萬安",
            target_title_contains=target_title,
            recorded_at=today,
            current_value=float(total),
            note=f"官方戰情中心當日：{notes}（共 {len(records)} 處建案）",
            source_url=URL,
            publisher=PUBLISHER,
            authority_level=1,
        ))
    print(f"  ✓ 抓到 {len(records)} 處建案，分類成 {len(matches)} 個子指標")
    return matches


def fetch_taipei_long_term_care() -> list[TargetMatch]:
    """臺北市立案住宿式長照機構 — 93 處機構、含核定床位數。

    資料源：data.taipei（衛生局）
    URL: https://data.taipei/api/dataset/d455b149-.../resource/2649f023-.../download
    更新頻率：不定期
    """
    URL = ("https://data.taipei/api/dataset/d455b149-1a2f-4d5a-a9a8-315eb71f51f6"
           "/resource/2649f023-26ce-483a-a6f9-d7854522bcfd/download")
    PUBLISHER = "臺北市衛生局（data.taipei）"
    today = date.today().isoformat()

    try:
        raw = _http_get(URL)
        text = raw.decode("utf-8-sig", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text)))
    except Exception as e:
        print(f"  ✗ 抓取失敗：{e}")
        return []

    if not rows:
        return []

    def _safe_int(v):
        try:
            return int((v or "0").strip())
        except (ValueError, AttributeError):
            return 0

    total_ltc = sum(_safe_int(r.get("長照床位數量")) for r in rows)
    total_beds = sum(_safe_int(r.get("核定總床位數量")) for r in rows)
    print(f"  ✓ 抓到 {len(rows)} 處機構：長照床位 {total_ltc} 張、核定總床位 {total_beds} 張")

    return [
        TargetMatch(
            person_name="蔣萬安",
            target_title_contains="長照床位",
            recorded_at=today,
            current_value=float(total_ltc),
            note=f"立案住宿式長照機構 {len(rows)} 處、長照床位累計 {total_ltc} 張",
            source_url=URL,
            publisher=PUBLISHER,
            authority_level=1,
        ),
    ]


def fetch_taipei_urban_renewal() -> list[TargetMatch]:
    """都更處未提供公開 API；目前以人工查詢為主。"""
    print("  · 都更處未提供開放 API（需人工查 https://gis.uro.taipei/）")
    return []


def fetch_national_social_housing() -> list[TargetMatch]:
    """內政部住宅資訊網（待研究）。"""
    print("  · 內政部住宅資訊網需爬蟲（待實作）")
    return []


SOURCES = [
    Source("taipei_social_housing", "臺北市社會住宅興辦進度", fetch_taipei_social_housing),
    Source("taipei_long_term_care", "臺北市立案住宿式長照機構", fetch_taipei_long_term_care),
    Source("taipei_urban_renewal", "臺北市公辦都更案件", fetch_taipei_urban_renewal),
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

        exists = conn.execute("""
            SELECT progress_id FROM platform_target_progress
            WHERE target_id = ? AND recorded_at = ?
        """, (target_id, m.recorded_at)).fetchone()

        if dry_run:
            status = "已存在會略過" if exists else "新增"
            print(f"    [dry] {m.target_title_contains} @ {m.recorded_at} = {m.current_value} ({status})")
            continue

        if exists:
            # 更新既有 progress 的數字、新增來源（多源並存）
            conn.execute("""
                UPDATE platform_target_progress
                SET current_value = ?, note = ?
                WHERE progress_id = ?
            """, (m.current_value, m.note, exists["progress_id"]))
            progress_id = exists["progress_id"]
            # 是否已有相同 URL 的來源
            dup_src = conn.execute("""
                SELECT source_id FROM platform_progress_sources
                WHERE progress_id = ? AND url = ?
            """, (progress_id, m.source_url)).fetchone()
            if not dup_src:
                conn.execute("""
                    INSERT INTO platform_progress_sources
                        (progress_id, url, source_type, publisher, authority_level)
                    VALUES (?, ?, 'gov_open_data', ?, ?)
                """, (progress_id, m.source_url, m.publisher, m.authority_level))
            print(f"    · 已更新 {m.target_title_contains} @ {m.recorded_at} = {m.current_value}")
            skipped += 1
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
        print(f"    ✓ 新增 {m.target_title_contains} @ {m.recorded_at} = {m.current_value}")
        inserted += 1

    conn.commit()
    conn.close()
    print(f"  → 新增 {inserted} 筆")


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
