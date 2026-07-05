"""
從政見內文自動抽取量化承諾（regex 版）。

★ 定位（2026-07-05 起）：本腳本為【稽核/dry-run 工具】，正式抽取管線是
  llm_extract_targets.py（LLM 原生理解中文數字，品質較高且有驗證欄位）。
  需要正式寫入時務必確認 extraction_method 隔離（本腳本只刪 'regex' rows）。

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

# 過去達成（已完成事項）
PAST_KEYWORDS = re.compile(
    r"已完成|已達成|已興建|已蓋|已建|已通過|已實施|已落實|已上路|"
    r"完工|啟用|過去四年|前任期內|去年|上半年|今年初|已採購|已輔導|"
    r"已補助|已上線|已開幕|已蓋好|已建好|已破土"
)

# 未來承諾（將要做）
FUTURE_KEYWORDS = re.compile(
    r"將|預計|計劃|規劃|未來|預定|承諾|爭取|推動|預期|"
    r"力拼|希望|盼|爭取|致力|準備|目標|預備|努力|"
    r"任內|4年內|四年內|2030|2028|2026"
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
    """確保 platform_targets 有 source_platform_id / tense 欄位。"""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(platform_targets)")]
    if "source_platform_id" not in cols:
        conn.execute("ALTER TABLE platform_targets ADD COLUMN source_platform_id INTEGER")
    if "auto_extracted" not in cols:
        conn.execute("ALTER TABLE platform_targets ADD COLUMN auto_extracted INTEGER DEFAULT 0")
    if "tense" not in cols:
        conn.execute("ALTER TABLE platform_targets ADD COLUMN tense TEXT")  # past/future/unknown
    if "extraction_method" not in cols:
        # regex / llm — 各管線只能刪自己的 rows，避免互相蓋掉
        conn.execute("ALTER TABLE platform_targets ADD COLUMN extraction_method TEXT")
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


# ── 中文數字支援 ─────────────────────────────────────────────────────────────
# 政見常見中文數字量化承諾（一萬名青年、三班護病比、一億元創業基金、五十公頃…）
_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_MULT = {"十": 10, "百": 100, "千": 1000, "萬": 10000, "億": 100000000}


def cn2num(s: str) -> float | None:
    """中文數字字串轉整數：一千五百萬→15000000、十二→12、三萬→30000。失敗回 None。"""
    total = section = number = 0
    for ch in s:
        if ch in _CN_DIGIT:
            number = _CN_DIGIT[ch]
        elif ch in _CN_MULT:
            u = _CN_MULT[ch]
            if u >= 10000:
                section = (section + number) * u
                total += section
                section = 0
            else:
                if number == 0 and ch == "十":  # 十二 → 12
                    number = 1
                section += number * u
            number = 0
        else:
            return None
    return total + section + number


# 中文數字開頭須為真數字(一~十/兩)，避免抓到裸的「萬戶/百萬」
_CN_NUM = r"[一二三四五六七八九十兩][一二三四五六七八九十百千萬億兩]*"
# 強單位：裸中文數字即可收（明確量化、少成語碰撞）
_CN_STRONG_UNITS = r"萬戶|千戶|戶|億元|兆元|萬元|公里|公頃|床|班|校|席"
# 弱單位：計數詞易與「一國/一例/統一處理」等成語碰撞，須數字含位數(十百千萬)才收
_CN_WEAK_UNITS = r"座|所|處|家|件|名|人"
_CN_PAT = re.compile(rf"(?P<num>{_CN_NUM})\s*(?P<unit>{_CN_STRONG_UNITS}|{_CN_WEAK_UNITS})")
_CN_STRONG_RE = re.compile(rf"^(?:{_CN_STRONG_UNITS})$")
_CN_MAG_RE = re.compile(r"[十百千萬億]")


def _build_target(sent: str, num: float, unit: str) -> dict:
    """把一個 (句子, 數值, 單位) 組成 target dict（topic/時程/時態共用）。"""
    topic = detect_topic(sent) or "未分類"
    time_horizon = None
    for tp in TIME_PATTERNS:
        tm = tp.search(sent)
        if tm:
            time_horizon = tm.group(0)
            break
    if PAST_KEYWORDS.search(sent):
        tense = "past"
    elif FUTURE_KEYWORDS.search(sent):
        tense = "future"
    else:
        tense = "unknown"
    return {
        "title": sent[:80] + ("…" if len(sent) > 80 else ""),
        "description": sent,
        "target_value": num,
        "metric_unit": unit,
        "time_horizon": time_horizon,
        "topic": topic,
        "tense": tense,
    }


def extract_targets(content: str) -> list[dict]:
    """從一段 content 切句子、找量化承諾（阿拉伯數字優先，中文數字為補充）。"""
    out = []
    sentences = re.split(r"[\n。！\?；]+", content)
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 5 or len(sent) > 300:
            continue
        # 要有行動詞，避免「過去 X 年」這種客觀陳述
        if not ACTION_KEYWORDS.search(sent):
            continue
        matched = False
        # 1) 阿拉伯數字 + 單位（原邏輯）
        for pat, unit, mult in UNIT_PATTERNS:
            m = pat.search(sent)
            if not m:
                continue
            num = to_number(m.group(1)) * mult
            if num < 1 or num > 1e10:
                continue
            out.append(_build_target(sent, num, unit))
            matched = True
            break  # 一句話只抽第一個量化承諾
        # 2) 中文數字 + 單位（阿拉伯沒抓到時才補）
        if not matched:
            for m in _CN_PAT.finditer(sent):
                num_str, unit = m.group("num"), m.group("unit")
                val = cn2num(num_str)
                if val is None or val < 1 or val > 1e10:
                    continue
                # 弱單位須含位數，擋掉裸「一人/一處」等成語誤判
                if not _CN_STRONG_RE.match(unit) and not _CN_MAG_RE.search(num_str):
                    continue
                out.append(_build_target(sent, val, unit))
                break
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

    # 只刪自己(regex)產的舊 rows；LLM 管線(extraction_method='llm')的 rows 絕不可刪
    # （2026-07-05 曾因無條件 DELETE auto_extracted=1 誤刪 1414 筆 LLM targets）
    if not args.dry_run:
        conn.execute(
            "DELETE FROM platform_targets WHERE auto_extracted = 1"
            " AND extraction_method = 'regex'"
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
                    auto_extracted, source_platform_id, tense, extraction_method)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'in_progress', 1, ?, ?, 'regex')""",
                (
                    r["person_name"],
                    r["election_id"],
                    t["topic"],
                    t["title"],
                    t["description"],
                    t["metric_unit"],
                    t["target_value"],
                    None,
                    r["platform_id"],
                    t["tense"],
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
