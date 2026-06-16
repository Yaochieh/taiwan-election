"""
從政見內文自動抽取量化承諾。

支援 patterns：
  - 數量單位：N 萬戶 / N 千戶 / N 戶 / N 億 / N 萬元 / N 件 / N 床 / N 人 / N 公里
  - 比例：N% / N 成
  - 時程：N 年內 / 任內

寫入 platform_targets 表（含 platform_id 來源）。
這些是「提取的承諾」，需後續配對開放資料追蹤達標。

執行：
  python scripts/extract_platform_targets.py [--dry-run] [--candidate NAME]
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
DB_PATH = ROOT / "data" / "db.sqlite"


# 數量單位模式（單位 → 中文人類可讀）
UNIT_PATTERNS: list[tuple[re.Pattern, str, float]] = [
    # 戶 / 床 / 件 / 人 / 名額 / 班 / 校
    (re.compile(r"(\d[\d,]*\.?\d*)\s*萬戶"), "戶", 10000),
    (re.compile(r"(\d[\d,]*\.?\d*)\s*千戶"), "戶", 1000),
    (re.compile(r"(\d[\d,]*\.?\d*)\s*戶"), "戶", 1),
    (re.compile(r"(\d[\d,]*\.?\d*)\s*萬人"), "人", 10000),
    (re.compile(r"(\d[\d,]*\.?\d*)\s*床"), "床位", 1),
    (re.compile(r"(\d[\d,]*\.?\d*)\s*家"), "家", 1),
    (re.compile(r"(\d[\d,]*\.?\d*)\s*萬"), "萬", 1),  # 廣義數值
    # 金額
    (re.compile(r"(\d[\d,]*\.?\d*)\s*億元"), "億元", 1),
    (re.compile(r"(\d[\d,]*\.?\d*)\s*兆元"), "兆元", 1),
    (re.compile(r"(\d[\d,]*\.?\d*)\s*萬元"), "萬元", 1),
    # 距離 / 面積
    (re.compile(r"(\d[\d,]*\.?\d*)\s*公里"), "公里", 1),
    (re.compile(r"(\d[\d,]*\.?\d*)\s*公頃"), "公頃", 1),
    # 比例
    (re.compile(r"(\d[\d,]*\.?\d*)\s*[%％]"), "%", 1),
    (re.compile(r"(\d)\s*成"), "成（10%）", 1),
]

# 時程
TIME_PATTERNS = [
    re.compile(r"(\d+)\s*年內"),
    re.compile(r"任內"),
    re.compile(r"4\s*年"),
    re.compile(r"年底前"),
]

# 行動詞（用來判斷這是承諾而非客觀陳述）
ACTION_KEYWORDS = re.compile(
    r"興建|新建|增加|提供|推動|完成|建設|達到|達成|建立|降低|減少|"
    r"提升|提高|擴大|減半|加倍|實施|實現|落實|引進|引入|納入|"
    r"輔導|補助|涵蓋|普及|興辦|擴增|擴建|採購"
)

# 主題關鍵字（讓 target 自動歸類到 platform_topics 已存在的主題）
TOPIC_KEYWORDS = {
    "住宅": ["社宅", "公宅", "社會住宅", "公辦都更", "都更", "包租代管", "青年住宅", "青安"],
    "長照": ["長照", "長期照顧", "失智", "失能", "銀髮", "樂齡", "日照中心"],
    "醫療": ["健保", "醫療", "醫院", "醫師", "癌症", "疫苗"],
    "教育": ["教育", "學校", "技職", "雙語", "托育", "幼兒"],
    "交通": ["捷運", "輕軌", "高鐵", "公車", "鐵道"],
    "環境能源": ["再生能源", "綠能", "核電", "減碳", "碳排"],
    "國防": ["國防", "軍購", "潛艦", "戰機"],
    "勞工就業": ["勞工", "薪資", "最低工資", "就業"],
}


def ensure_target_columns(conn):
    """確保 platform_targets 有 source_platform_id 欄位。"""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(platform_targets)")]
    if "source_platform_id" not in cols:
        conn.execute("ALTER TABLE platform_targets ADD COLUMN source_platform_id INTEGER")
    if "auto_extracted" not in cols:
        conn.execute("ALTER TABLE platform_targets ADD COLUMN auto_extracted INTEGER DEFAULT 0")
    conn.commit()


def to_number(s: str) -> float:
    return float(s.replace(",", ""))


def detect_topic(text: str) -> str | None:
    """判斷該段文字的主題。"""
    best = None
    best_score = 0
    for topic, kws in TOPIC_KEYWORDS.items():
        s = sum(text.count(kw) for kw in kws)
        if s > best_score:
            best_score = s
            best = topic
    return best


def extract_targets(content: str) -> list[dict]:
    """從一段 content 切句子、找量化承諾。"""
    out = []
    # 句子切分
    sentences = re.split(r"[\n。！\?；]+", content)
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 5 or len(sent) > 300:
            continue
        # 必須有行動詞或數字後跟單位
        for pat, unit, mult in UNIT_PATTERNS:
            m = pat.search(sent)
            if not m:
                continue
            num = to_number(m.group(1)) * mult
            # 過小或過大都不取
            if num < 1 or num > 1e10:
                continue
            # 要有行動詞，避免「過去 X 年」這種
            if not ACTION_KEYWORDS.search(sent):
                continue
            topic = detect_topic(sent) or "未分類"
            # 時程
            time_horizon = None
            for tp in TIME_PATTERNS:
                tm = tp.search(sent)
                if tm:
                    time_horizon = tm.group(0)
                    break
            out.append(
                {
                    "title": sent[:80] + ("…" if len(sent) > 80 else ""),
                    "description": sent,
                    "target_value": num,
                    "metric_unit": unit,
                    "time_horizon": time_horizon,
                    "topic": topic,
                }
            )
            break  # 一句話只抽第一個量化承諾
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--candidate", help="只處理特定候選人")
    ap.add_argument("--limit", type=int, help="只處理前 N 條政見")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_target_columns(conn)

    where = ""
    params: list = []
    if args.candidate:
        where = " WHERE c.name = ?"
        params.append(args.candidate)

    sql = f"""
        SELECT p.platform_id, p.candidate_id, p.election_id, p.content,
               c.name AS person_name, e.date AS election_date
        FROM platforms p
        JOIN candidates c ON p.candidate_id = c.candidate_id
        JOIN elections e ON p.election_id = e.election_id
        {where}
        ORDER BY p.platform_id
    """
    if args.limit:
        sql += f" LIMIT {args.limit}"

    rows = conn.execute(sql, params).fetchall()
    print(f"📋 {len(rows)} 條政見要解析")

    # 刪除舊的 auto_extracted
    if not args.dry_run:
        conn.execute(
            "DELETE FROM platform_targets WHERE auto_extracted = 1"
            + (" AND person_name = ?" if args.candidate else ""),
            (args.candidate,) if args.candidate else (),
        )
        conn.commit()

    total_targets = 0
    per_person: dict[str, int] = {}
    for r in rows:
        targets = extract_targets(r["content"] or "")
        if not targets:
            continue
        per_person[r["person_name"]] = per_person.get(r["person_name"], 0) + len(targets)
        if args.dry_run:
            for t in targets[:1]:
                print(f"  {r['person_name']}: [{t['topic']}] {t['target_value']:.0f} {t['metric_unit']} "
                      f"{t['time_horizon'] or ''} — {t['title'][:60]}")
            continue
        for t in targets:
            conn.execute(
                """INSERT INTO platform_targets
                   (person_name, election_id, category, title, description,
                    metric_unit, target_value, target_date, status,
                    auto_extracted, source_platform_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'in_progress', 1, ?)""",
                (
                    r["person_name"],
                    r["election_id"],
                    t["topic"],
                    t["title"],
                    t["description"],
                    t["metric_unit"],
                    t["target_value"],
                    None,  # target_date — could parse from time_horizon
                    r["platform_id"],
                ),
            )
            total_targets += 1
    if not args.dry_run:
        conn.commit()

    print(f"\n✓ 抽出 {total_targets} 個量化承諾")
    print("\n按候選人 Top 15：")
    for name, n in sorted(per_person.items(), key=lambda x: -x[1])[:15]:
        print(f"  {name}: {n}")
    conn.close()


if __name__ == "__main__":
    main()
