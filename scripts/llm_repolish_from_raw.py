"""
還原 split 前的原始 OCR，重新對「每個候選人 × 每場選舉」跑 LLM 一次。

策略：
1. 找出有多條 LLM 政見的 (candidate, election) — 都是當初 split 切出來的
2. 抓 seq=1 的 content_raw（split 時把原始 OCR 整段塞在那）
3. 刪掉這位候選人在這場選舉的所有政見
4. 對 content_raw 跑 LLM 一次 → 取得整理好的清單 + 量化目標
5. 寫回單一 seq=1 entry

對「只有 1 條 LLM 政見」者完全不動。
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"
ENV_FILE = ROOT / ".env"

if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not API_KEY:
    print("ERR: ANTHROPIC_API_KEY 未設定"); sys.exit(1)

from anthropic import Anthropic
client = Anthropic(api_key=API_KEY)
MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """你會收到一位台灣選舉候選人公報的完整 OCR 原文（有時段落很長、包含學歷經歷雜訊）。

請整理成乾淨政見清單：
1. **去除雜訊**：拿掉學歷、經歷、政黨 slogan、頁碼、亂碼、英文 slogan
2. **抽 5-10 條政見**：每條格式「N. 主題：具體內容」
3. **去重**：同樣承諾不要重複列出
4. **抽量化承諾**：「N 萬戶」「N 億元」「N% 比例」「N 年內」這種具體數字都要抽出來
5. **不要新增**原文沒有的承諾

**重要：分辨「政績」vs「承諾」**：
- 「已成功爭取/已完成/近 X 年爭取/已通過」= 政績（過去式）→ tense="past"
- 「將推動/承諾/未來會/上任後/將爭取」= 承諾（未來式）→ tense="future"
- 政績不需要追蹤，承諾才需要

若原文無有效政見，輸出 polished_content = "（公報無有效政見內容）"。

輸出 JSON（無 markdown wrap）：
{
  "polished_content": "1. ...\\n2. ...",
  "targets": [{
    "topic": "...",
    "title": "...",
    "value": 數字,
    "unit": "戶/萬/%/...",
    "context": "...",
    "tense": "past" or "future"
  }]
}"""


def polish(person: str, election_label: str, raw: str) -> dict:
    msg = client.messages.create(
        model=MODEL, max_tokens=3000, system=SYSTEM,
        messages=[{
            "role": "user",
            "content": f"候選人：{person}\n選舉：{election_label}\n\n公報 OCR 原文：\n---\n{raw}\n---",
        }],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"polished_content": text[:2000], "targets": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    groups = conn.execute("""
        SELECT c.candidate_id, c.name, p.election_id,
               e.date, e.name AS election_name, e.description,
               COUNT(*) AS n
        FROM platforms p
        JOIN candidates c ON c.candidate_id=p.candidate_id
        JOIN elections e ON e.election_id=p.election_id
        WHERE p.note LIKE '%LLM%'
        GROUP BY p.candidate_id, p.election_id
        HAVING n > 1
        ORDER BY n DESC
    """).fetchall()
    if args.limit:
        groups = groups[: args.limit]
    print(f"待重跑 {len(groups)} 組（每組 1 次 LLM call）")

    today = date.today().isoformat()
    tag = f"[LLM 潤稿 by Claude haiku {today}]"

    for i, g in enumerate(groups, 1):
        # 抓 seq=1 的 content_raw（原始 OCR）
        first = conn.execute(
            "SELECT platform_id, content_raw FROM platforms "
            "WHERE candidate_id=? AND election_id=? ORDER BY seq LIMIT 1",
            (g["candidate_id"], g["election_id"]),
        ).fetchone()
        if not first or not first["content_raw"] or len(first["content_raw"]) < 30:
            print(f"\n[{i}/{len(groups)}] {g['name']}: 沒有原始 OCR，跳過")
            continue
        raw = first["content_raw"]
        election_label = f"{g['date'][:7]} {g['election_name']} {g['description'] or ''}"
        print(f"\n[{i}/{len(groups)}] {g['name']} (election {g['election_id']}): "
              f"原 OCR {len(raw)} 字 → 1 LLM call")
        try:
            result = polish(g["name"], election_label, raw)
            polished = result.get("polished_content", "").strip()
            targets = result.get("targets", [])
            print(f"  ✓ 政見 {len(polished)} 字、量化 {len(targets)}")
            if args.dry_run:
                print("--- polished ---")
                print(polished[:600])
                if targets:
                    print("--- targets ---")
                    print(json.dumps(targets, ensure_ascii=False, indent=2)[:500])
                continue
            # 刪掉這候選人在這選舉所有政見、舊 targets
            old_pids = [r["platform_id"] for r in conn.execute(
                "SELECT platform_id FROM platforms WHERE candidate_id=? AND election_id=?",
                (g["candidate_id"], g["election_id"]),
            ).fetchall()]
            if old_pids:
                conn.execute(
                    "DELETE FROM platform_targets "
                    "WHERE source_platform_id IN (%s)" % ",".join("?" * len(old_pids)),
                    old_pids,
                )
                conn.execute(
                    "DELETE FROM platforms WHERE platform_id IN (%s)"
                    % ",".join("?" * len(old_pids)),
                    old_pids,
                )
            # 插入單一新 entry
            cur = conn.execute(
                """INSERT INTO platforms
                   (candidate_id, election_id, seq, content, content_raw, note)
                   VALUES (?, ?, 1, ?, ?, ?)""",
                (g["candidate_id"], g["election_id"], polished, raw, tag),
            )
            new_pid = cur.lastrowid
            for t in targets:
                try:
                    conn.execute(
                        """INSERT INTO platform_targets
                           (person_name, election_id, category, title, description,
                            metric_unit, target_value, source_platform_id, auto_extracted, tense)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                        (g["name"], g["election_id"], t.get("topic"),
                         t.get("title", "")[:120], t.get("context", ""),
                         t.get("unit"), t.get("value"), new_pid,
                         t.get("tense", "unknown")),
                    )
                except sqlite3.Error:
                    pass
            conn.commit()
            time.sleep(0.3)
        except Exception as e:
            print(f"  ✗ {e}")
            time.sleep(2)
    conn.close()
    print("\n完成")


if __name__ == "__main__":
    main()
