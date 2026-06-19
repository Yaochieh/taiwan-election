"""2024不分區16政黨：用真實 content_raw(OCR原文)重新LLM潤稿,取代手寫content。
content_raw='占位'(民進黨)的從不分區PDF重OCR。

用法：python scripts/repolish_partylist.py
"""
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "db.sqlite"
ENV = ROOT / ".env"
if ENV.exists():
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
from anthropic import Anthropic
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """你會收到一個台灣政黨在不分區立委選舉公報的 OCR 原文(含政黨政見+候選人個資雜訊)。
請整理出該政黨的政見:去雜訊(候選人學歷經歷/姓名/亂碼),整理5-12條「N. 主題：內容」,不編造。
若OCR無有效政見內容,回「（公報無有效政見內容）」。只輸出政見文字,不要JSON。"""


def polish(party: str, raw: str) -> str:
    msg = client.messages.create(
        model=MODEL, max_tokens=2000, system=SYSTEM,
        messages=[{"role": "user", "content": f"政黨：{party}\n\nOCR原文：\n{raw[:12000]}"}])
    return "".join(b.text for b in msg.content if hasattr(b, "text")).strip()


def main():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT p.platform_id, c.name, p.content_raw FROM platforms p "
        "JOIN candidates c ON c.candidate_id=p.candidate_id "
        "WHERE p.election_id=50 AND length(c.name)>3").fetchall()
    n = 0
    for r in rows:
        raw = r["content_raw"] or ""
        if len(raw) < 20 or raw == "占位":
            print(f"  - {r['name']}: content_raw 太短/占位({len(raw)}字),跳過(需重OCR)")
            continue
        try:
            content = polish(r["name"], raw)
        except Exception as e:
            print(f"  ✗ {r['name']}: {e}"); continue
        if "無有效政見" in content or len(content) < 30:
            print(f"  - {r['name']}: 無有效政見"); continue
        conn.execute("UPDATE platforms SET content=?, note=? WHERE platform_id=?",
                     (content, "[LLM 潤稿 by Claude haiku 2026-06-19]", r["platform_id"]))
        n += 1
        print(f"  ✓ {r['name']}: {len(content)} 字")
    conn.commit()
    print(f"\n重潤稿 {n} 個政黨(從真實OCR)")
    conn.close()


if __name__ == "__main__":
    main()
