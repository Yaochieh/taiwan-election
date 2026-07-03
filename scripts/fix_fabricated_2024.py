"""清除 2024 立委 40 條「人工潤稿」腦補政見（content 是政黨模板，與 content_raw 真實 OCR 無關）。

處理：content_raw 有實質政見 → 用嚴格 prompt 從 content_raw 重潤 + 80% 4-gram overlap 驗證；
     content_raw 太短或非政見或 overlap 不過 → 刪除 platform（前端 fallback 圖片政見/從缺）。
連動 platform_targets（腦補 content 抽的量化目標）一併刪除，重潤成功者重抽。

用法：python scripts/fix_fabricated_2024.py [--dry-run]
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

from anthropic import Anthropic  # noqa: E402
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """你是OCR文字整理員。下面是一位台灣立委候選人選舉公報的OCR原文。
【絕對規則】只能用OCR原文裡「實際出現的字句」整理政見條列，不改寫措辭、不摘要、不補充。
嚴禁加入OCR沒有的政見、數字、承諾。你不是在寫政見，只是把OCR裡的政見片段去雜訊(學經歷/姓名/亂碼)後條列。
若OCR原文只有學經歷、沒有政見內容，polished_content 輸出空字串。寧可少不可加。

同時抽OCR原文裡實際出現的量化承諾(「N萬戶」「N億元」「N%」「N年內」)。

輸出JSON(無markdown wrap)：
{"polished_content": "1. ...\\n2. ...",
 "targets": [{"topic":"...","title":"...","value":數字,"unit":"...","context":"...","tense":"past"或"future"}]}"""


def overlap_ratio(text: str, source: str) -> float:
    t = re.sub(r"[\s\d。，、：（）()【】「」\.]", "", text)
    s = re.sub(r"[\s\d。，、：（）()【】「」\.]", "", source)
    if len(t) < 4:
        return 0.0
    grams = [t[i:i+4] for i in range(len(t) - 3)]
    return sum(1 for g in grams if g in s) / len(grams) if grams else 0.0


def delete_platform(conn, pid):
    conn.execute("DELETE FROM platform_targets WHERE source_platform_id=?", (pid,))
    conn.execute("DELETE FROM platforms WHERE platform_id=?", (pid,))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT p.platform_id, p.candidate_id, p.election_id, p.content_raw, c.name "
        "FROM platforms p JOIN candidates c ON p.candidate_id=c.candidate_id "
        "WHERE p.note LIKE '%人工潤稿%' ORDER BY p.platform_id").fetchall()
    print(f"待處理 {len(rows)} 條腦補政見")
    today = date.today().isoformat()
    tag = f"[LLM 潤稿 by Claude haiku {today} 從content_raw重潤,80%重疊驗證] 取代原人工潤稿模板"
    fixed = deleted = 0
    for r in rows:
        raw = (r["content_raw"] or "").strip()
        if len(raw) < 200:
            print(f"✗ {r['name']}: raw僅{len(raw)}字 → 刪除")
            if not args.dry_run:
                delete_platform(conn, r["platform_id"])
            deleted += 1
            continue
        msg = client.messages.create(model=MODEL, max_tokens=3000, system=SYSTEM,
            messages=[{"role": "user", "content": f"候選人：{r['name']}\n\nOCR原文：\n{raw[:15000]}"}])
        t = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
        t = re.sub(r"^```(?:json)?\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
        try:
            seg = json.loads(t)
        except json.JSONDecodeError:
            print(f"✗ {r['name']}: LLM沒回JSON → 刪除")
            if not args.dry_run:
                delete_platform(conn, r["platform_id"])
            deleted += 1
            continue
        polished = (seg.get("polished_content") or "").strip()
        ratio = overlap_ratio(polished, raw)
        if len(polished) < 30 or ratio < 0.80:
            print(f"✗ {r['name']}: 政見{len(polished)}字 重疊{ratio:.0%} → 刪除")
            if not args.dry_run:
                delete_platform(conn, r["platform_id"])
            deleted += 1
            continue
        print(f"✓ {r['name']}: {len(polished)}字 (重疊{ratio:.0%}) targets {len(seg.get('targets', []))}")
        if args.dry_run:
            continue
        conn.execute("DELETE FROM platform_targets WHERE source_platform_id=?", (r["platform_id"],))
        conn.execute("UPDATE platforms SET content=?, note=? WHERE platform_id=?",
                     (polished, tag, r["platform_id"]))
        for tg in seg.get("targets", []):
            if not isinstance(tg, dict) or not tg.get("title"):
                continue
            conn.execute(
                "INSERT INTO platform_targets (person_name, election_id, category, title, description, "
                "metric_unit, target_value, source_platform_id, auto_extracted, tense) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (r["name"], r["election_id"], tg.get("topic"), str(tg.get("title"))[:120],
                 tg.get("context", ""), tg.get("unit"), tg.get("value"),
                 r["platform_id"], tg.get("tense", "unknown")))
        conn.commit()
        time.sleep(0.3)
        fixed += 1
    if not args.dry_run:
        conn.commit()
    conn.close()
    print(f"\n重潤 {fixed} 條、刪除 {deleted} 條（腦補模板全清）")


if __name__ == "__main__":
    main()
