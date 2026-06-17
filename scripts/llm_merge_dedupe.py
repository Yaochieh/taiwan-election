"""
把同一候選人同一場選舉的多條 LLM 潤稿政見，合併成一條乾淨的政見清單。

之前 split_multi_bullet_platforms 把長 OCR 切多條 → 每條都被 LLM 整成 5-8 bullet
→ 同候選人重複嚴重。這個腳本把它們合併成單一 seq=1 entry，去重 + 抽量化目標。

用法：python scripts/llm_merge_dedupe.py [--dry-run]
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
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not API_KEY:
    print("ERR: ANTHROPIC_API_KEY", file=sys.stderr); sys.exit(1)

from anthropic import Anthropic
client = Anthropic(api_key=API_KEY)
MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """你會收到一位台灣選舉候選人在同一場選舉的「多份重複/重疊」的政見條列（之前自動拆條造成的）。

請合併成一份乾淨統一的政見清單：
1. 去除重複（同主題、同數字、同承諾只保留一份且寫最完整的版本）
2. 整理為 5-10 條（不要超過 10）
3. 每條格式：「N. 主題：具體內容」
4. **抽量化承諾**：任何「N 萬戶」「N 億元」「N% 比例」「N 年內」等具體數字都抽出來
5. **不要新增**原文沒有的承諾

輸出 JSON：
{
  "polished_content": "1. ...\\n2. ...",
  "targets": [{"topic": "...", "title": "...", "value": 數字, "unit": "戶/萬/%/...", "context": "..."}]
}"""


def merge_candidate(person: str, election_label: str, contents: list[str]) -> dict:
    joined = "\n\n===\n\n".join(contents)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": f"候選人：{person}\n選舉：{election_label}\n\n以下是多份重複的條列政見，請合併去重：\n\n{joined}",
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
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    groups = conn.execute("""
        SELECT c.candidate_id, c.name, p.election_id,
               e.date, e.name AS election_name, e.description,
               COUNT(*) AS n,
               GROUP_CONCAT(p.platform_id, ',') AS plat_ids
        FROM platforms p
        JOIN candidates c ON c.candidate_id=p.candidate_id
        JOIN elections e ON e.election_id=p.election_id
        WHERE p.note LIKE '%LLM%'
        GROUP BY p.candidate_id, p.election_id
        HAVING n > 1
        ORDER BY n DESC
    """).fetchall()
    print(f"待合併 {len(groups)} 組")

    today = date.today().isoformat()
    tag = f"[LLM 潤稿+去重 by Claude haiku {today}]"

    for i, g in enumerate(groups, 1):
        plat_ids = [int(x) for x in g["plat_ids"].split(",")]
        # 抓所有 content
        contents = []
        for pid in plat_ids:
            row = conn.execute(
                "SELECT content FROM platforms WHERE platform_id=?",
                (pid,),
            ).fetchone()
            if row and row["content"] and "（公報無有效政見內容）" not in row["content"]:
                contents.append(row["content"])
        if not contents:
            continue
        election_label = f"{g['date'][:7]} {g['election_name']} {g['description'] or ''}"
        print(f"\n[{i}/{len(groups)}] {g['name']} (election {g['election_id']}): {len(contents)} 條")
        try:
            result = merge_candidate(g["name"], election_label, contents)
            polished = result.get("polished_content", "").strip()
            targets = result.get("targets", [])
            print(f"  ✓ 合併後 {len(polished)} 字，量化 {len(targets)}")
            if args.dry_run:
                print("--- merged ---")
                print(polished[:500])
                continue
            # 保留 seq=1，內容換成合併版；其他 seq 刪除
            first_pid = plat_ids[0]
            content_raw = conn.execute(
                "SELECT GROUP_CONCAT(COALESCE(content_raw, content), char(10)) "
                "FROM platforms WHERE platform_id IN (%s)" % ",".join("?" * len(plat_ids)),
                plat_ids,
            ).fetchone()[0]
            conn.execute(
                "UPDATE platforms SET content=?, content_raw=?, note=?, seq=1 WHERE platform_id=?",
                (polished, content_raw, tag, first_pid),
            )
            # 刪其他
            other = [p for p in plat_ids if p != first_pid]
            if other:
                conn.execute(
                    "DELETE FROM platforms WHERE platform_id IN (%s)"
                    % ",".join("?" * len(other)),
                    other,
                )
                # 同步 platform_targets source_platform_id 也指到 first_pid
                conn.execute(
                    "UPDATE platform_targets SET source_platform_id=? "
                    "WHERE source_platform_id IN (%s)" % ",".join("?" * len(other)),
                    [first_pid] + other,
                )
            # 補新的 targets
            for t in targets:
                try:
                    conn.execute(
                        """INSERT INTO platform_targets
                           (person_name, election_id, category, title, description,
                            metric_unit, target_value, source_platform_id, auto_extracted)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                        (g["name"], g["election_id"], t.get("topic"),
                         t.get("title", "")[:120], t.get("context", ""),
                         t.get("unit"), t.get("value"), first_pid),
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
