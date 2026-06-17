"""對已潤稿政見 (人工或 LLM)，抽量化目標 + 標 tense (past/future)。

不修改 content，只增 platform_targets。

用法：python scripts/llm_extract_targets.py [--limit N] [--dry-run]
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
ENV = ROOT / ".env"

if ENV.exists():
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not API_KEY:
    print("ERR"); sys.exit(1)
from anthropic import Anthropic
client = Anthropic(api_key=API_KEY)
MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """你會收到一位台灣選舉候選人已整理的政見清單。

請抽出量化目標 + 政績區分：
1. **抽出所有政見**（不論有沒有數字）：每條都列出來
2. **判 tense**：
   - past = 政績（已完成、已爭取、近 X 年）
   - future = 承諾（將推動、上任後、目標、規劃）
   - unknown = 模糊
3. **抽具體數字**（有的話）：「N 萬戶」「N 億元」「N%」「N 年內」

輸出 JSON（無 markdown wrap）：
{
  "items": [
    {
      "topic": "住宅/長照/教育/...",
      "title": "短標題 (主題：值 單位)",
      "description": "原條政見內容",
      "tense": "past" or "future" or "unknown",
      "value": 數字 or null,
      "unit": "戶/萬/%/..." or null
    }
  ]
}"""


def extract(person: str, content: str) -> dict:
    msg = client.messages.create(
        model=MODEL, max_tokens=2000, system=SYSTEM,
        messages=[{
            "role": "user",
            "content": f"候選人：{person}\n\n政見清單：\n{content}",
        }],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"items": []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    # 找出有政見 + 沒抽過 target 的 (candidate, election)
    rows = conn.execute("""
        SELECT p.platform_id, p.candidate_id, p.election_id, p.content,
               c.name AS candidate_name, e.date, e.name AS election_name, e.description
        FROM platforms p
        JOIN candidates c ON c.candidate_id=p.candidate_id
        JOIN elections e ON e.election_id=p.election_id
        WHERE length(p.content) > 50
          AND (p.note LIKE '%人工潤稿%' OR p.note LIKE '%LLM%')
          AND NOT EXISTS (
            SELECT 1 FROM platform_targets pt
            WHERE pt.person_name = c.name AND pt.election_id = p.election_id
              AND pt.auto_extracted = 1 AND pt.tense IS NOT NULL
          )
        ORDER BY e.date DESC, p.candidate_id, p.seq
    """).fetchall()
    # 按 (candidate, election) group 起來
    groups = {}
    for r in rows:
        key = (r["candidate_id"], r["election_id"])
        if key not in groups:
            groups[key] = {
                "candidate_name": r["candidate_name"],
                "election_id": r["election_id"],
                "election_date": r["date"],
                "election_name": r["election_name"],
                "election_desc": r["description"],
                "first_pid": r["platform_id"],
                "contents": [],
            }
        groups[key]["contents"].append(r["content"])
    items = list(groups.values())
    if args.limit:
        items = items[: args.limit]
    print(f"待抽 target：{len(items)} 組 (候選人 x 選舉)")

    for i, g in enumerate(items, 1):
        combined = "\n\n".join(g["contents"])
        if len(combined) > 8000:
            combined = combined[:8000]
        print(f"\n[{i}/{len(items)}] {g['candidate_name']} ({g['election_date'][:7]} {g['election_name']})")
        try:
            result = extract(g["candidate_name"], combined)
            its = result.get("items", [])
            print(f"  ✓ 抽出 {len(its)} 條（"
                  f"past {sum(1 for x in its if x.get('tense')=='past')} / "
                  f"future {sum(1 for x in its if x.get('tense')=='future')} / "
                  f"with_value {sum(1 for x in its if x.get('value') is not None)})")
            if args.dry_run:
                for it in its[:3]:
                    print(f"    - [{it.get('tense')}] {it.get('title')}: {(it.get('description') or '')[:60]}")
                continue
            for it in its:
                try:
                    conn.execute(
                        """INSERT INTO platform_targets
                           (person_name, election_id, category, title, description,
                            metric_unit, target_value, source_platform_id,
                            auto_extracted, tense, verification_status)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                        (g["candidate_name"], g["election_id"], it.get("topic"),
                         (it.get("title") or "")[:120], it.get("description"),
                         it.get("unit"), it.get("value"), g["first_pid"],
                         it.get("tense", "unknown"),
                         "pending" if it.get("tense") == "past" else None),
                    )
                except sqlite3.Error as e:
                    print(f"  ✗ insert: {e}")
            conn.commit()
            time.sleep(0.3)
        except Exception as e:
            print(f"  ✗ {e}")
            time.sleep(2)
    conn.close()
    print("\n完成")


if __name__ == "__main__":
    main()
