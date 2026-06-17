"""對 platform_targets 裡 tense 為 NULL/unknown 的條目，用 LLM 補上 past/future。

用法：python scripts/llm_tag_target_tense.py [--dry-run]
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
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
    print("ERR: ANTHROPIC_API_KEY"); sys.exit(1)
from anthropic import Anthropic
client = Anthropic(api_key=API_KEY)
MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """你會收到一條台灣選舉候選人公報抽出的政見/政績條目，包含 title、description。

請判斷這條是「政績」還是「承諾」：
- past（政績）：已成功爭取、已完成、已通過、近 X 年爭取到、爭取過、推動過
- future（承諾）：將推動、承諾、未來會、上任後、目標、預計、規劃
- unknown：原文模糊無法判斷

只輸出單一字串：past 或 future 或 unknown，不要其他文字。"""


def classify(title: str, desc: str) -> str:
    msg = client.messages.create(
        model=MODEL, max_tokens=10, system=SYSTEM,
        messages=[{
            "role": "user",
            "content": f"title: {title}\ndescription: {desc}",
        }],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip().lower()
    text = re.sub(r"[^a-z]", "", text)
    return text if text in ("past", "future", "unknown") else "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT target_id, title, description
        FROM platform_targets
        WHERE tense IS NULL OR tense = 'unknown'
    """).fetchall()
    print(f"待分類 {len(rows)}")
    counts = {"past": 0, "future": 0, "unknown": 0}
    for i, r in enumerate(rows, 1):
        try:
            tense = classify(r["title"] or "", r["description"] or "")
            counts[tense] += 1
            if args.dry_run:
                print(f"[{i}/{len(rows)}] {tense}: {(r['title'] or '')[:40]}")
                continue
            conn.execute(
                "UPDATE platform_targets SET tense=? WHERE target_id=?",
                (tense, r["target_id"]),
            )
            if tense == "past":
                conn.execute(
                    "UPDATE platform_targets SET verification_status='pending' "
                    "WHERE target_id=? AND verification_status IS NULL",
                    (r["target_id"],),
                )
            conn.commit()
            if i % 20 == 0:
                print(f"  進度 {i}/{len(rows)} (past {counts['past']} / future {counts['future']} / unknown {counts['unknown']})")
            time.sleep(0.1)
        except Exception as e:
            print(f"  ✗ #{r['target_id']}: {e}")
            time.sleep(1)
    print(f"\n完成：past {counts['past']} / future {counts['future']} / unknown {counts['unknown']}")
    conn.close()


if __name__ == "__main__":
    main()
