"""
用 Claude API 對未潤稿的政見做結構化整理。

每條政見：
  1. 原始 OCR/拆條後內容 → LLM
  2. LLM 輸出 JSON: {polished_content, extracted_targets}
  3. 寫回 platforms.content（保留 content_raw）
  4. 把 extracted_targets 寫入 platform_targets

用法：
  python scripts/llm_polish_platforms.py --limit 5         # dry run 5 條
  python scripts/llm_polish_platforms.py --limit 100       # 跑 100 條
  python scripts/llm_polish_platforms.py --model haiku     # 用 Haiku（預設）
  python scripts/llm_polish_platforms.py --model sonnet    # 用 Sonnet
  python scripts/llm_polish_platforms.py                   # 跑全部未潤稿
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

# 讀 .env 補進 environment
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not API_KEY:
    print("ERR: ANTHROPIC_API_KEY 未設定（試過 .env 也沒）", file=sys.stderr)
    sys.exit(1)

try:
    from anthropic import Anthropic
except ImportError:
    print("ERR: pip install anthropic", file=sys.stderr)
    sys.exit(1)

MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-8",
}

SYSTEM_PROMPT = """你會收到一位台灣選舉候選人公報上的政見文字（OCR 結果，可能有錯字、雜訊、政黨 slogan 等）。

你的任務：
1. **去除雜訊**：拿掉非政見內容（候選人姓名、學歷經歷、政黨 slogan、英文 slogan、頁碼、亂碼）。
2. **結構化整理**：整理成 5-8 條條列政見，每條格式：「N. 主題：具體內容」。
3. **保持忠實**：不要新增原文沒有的承諾。如果 OCR 太破不確定原意，寫進 uncertain_notes 不要亂猜。
4. **抽取量化承諾**：如有「N 萬戶」「N% 比例」「N 年內」等具體數字，抽出來。
5. **修常見 OCR 錯**：「公末」→「公宅」、「託育」→「托育」、「萬戶」「億元」等保留。

輸出 JSON 物件（不要 markdown wrap）：
{
  "polished_content": "1. 主題A：...\\n2. 主題B：...\\n...",
  "targets": [
    {"topic": "住宅", "title": "社宅 8 年 25 萬戶", "value": 250000, "unit": "戶", "context": "8 年內完成"}
  ],
  "uncertain_notes": "（若有對 OCR 看不懂的部分，寫這裡）"
}

若原文完全是雜訊無法萃取任何政見，輸出 `{"polished_content": "（公報無有效政見內容）", "targets": [], "uncertain_notes": "OCR 結果無法辨識"}`。
"""


def build_user_prompt(candidate_name: str, election_label: str, raw: str) -> str:
    return f"""候選人：{candidate_name}
選舉：{election_label}

公報 OCR 原文：
---
{raw}
---

請整理為 JSON。"""


def call_llm(client: Anthropic, model: str, candidate: str, election: str, raw: str) -> dict:
    msg = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": build_user_prompt(candidate, election, raw)}
        ],
    )
    text = "".join(
        b.text for b in msg.content if hasattr(b, "text")
    ).strip()
    # 拿掉可能的 markdown wrap
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "polished_content": text[:1500],
            "targets": [],
            "uncertain_notes": "LLM 沒回 JSON",
        }


def fetch_targets() -> list:
    """挑出尚未潤稿（含 OCR）的政見，按候選人聚合（同一人多條合併送一次）"""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT
          p.platform_id,
          p.candidate_id,
          p.election_id,
          p.seq,
          p.content,
          p.content_raw,
          p.note,
          c.name AS candidate_name,
          e.date AS election_date,
          e.name AS election_name,
          e.description AS election_desc
        FROM platforms p
        JOIN candidates c ON c.candidate_id = p.candidate_id
        JOIN elections e ON e.election_id = p.election_id
        WHERE (p.note IS NULL OR p.note NOT LIKE '%人工潤稿%' AND p.note NOT LIKE '%LLM%')
          AND length(COALESCE(p.content_raw, p.content)) > 30
        ORDER BY e.date DESC, p.candidate_id, p.seq
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_result(platform_id: int, polished: str, note_tag: str, targets: list,
                candidate_id: int, election_id: int, person_name: str):
    conn = sqlite3.connect(DB)
    conn.execute(
        "UPDATE platforms SET content=?, note=? WHERE platform_id=?",
        (polished, note_tag, platform_id),
    )
    for t in targets:
        try:
            conn.execute(
                """INSERT INTO platform_targets
                   (person_name, election_id, category, title, description,
                    metric_unit, target_value, source_platform_id, auto_extracted,
                    extraction_method)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'llm')""",
                (
                    person_name,
                    election_id,
                    t.get("topic"),
                    t.get("title", "")[:120],
                    t.get("context", ""),
                    t.get("unit"),
                    t.get("value"),
                    platform_id,
                ),
            )
        except sqlite3.Error:
            pass
    conn.commit()
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--model", default="haiku", choices=list(MODELS))
    ap.add_argument("--dry-run", action="store_true",
                    help="只印出，不寫回 DB")
    args = ap.parse_args()

    client = Anthropic(api_key=API_KEY)
    model = MODELS[args.model]
    today = date.today().isoformat()
    note_tag = f"[LLM 潤稿 by Claude {args.model} {today}]"

    targets = fetch_targets()
    if args.limit:
        targets = targets[: args.limit]
    print(f"待處理 {len(targets)} 條政見，使用 {model}")

    total_in = total_out = 0
    for i, r in enumerate(targets, 1):
        raw = r["content_raw"] or r["content"]
        election = f"{r['election_date'][:7]} {r['election_name']} {r['election_desc'] or ''}"
        try:
            print(f"\n[{i}/{len(targets)}] {r['candidate_name']} (#{r['platform_id']})")
            result = call_llm(client, model, r["candidate_name"], election, raw)
            polished = result.get("polished_content", "").strip()
            if not polished:
                print("  - 空輸出，跳過")
                continue
            print(f"  ✓ 政見 {len(polished)} 字，量化目標 {len(result.get('targets', []))} 個")
            if args.dry_run:
                print("--- polished ---")
                print(polished)
                print("--- targets ---")
                print(json.dumps(result.get("targets", []),
                                 ensure_ascii=False, indent=2))
                continue
            save_result(
                r["platform_id"],
                polished,
                note_tag,
                result.get("targets", []),
                r["candidate_id"],
                r["election_id"],
                r["candidate_name"],
            )
            # 簡單 rate limit
            time.sleep(0.3)
        except Exception as e:
            print(f"  ✗ {e}")
            time.sleep(2.0)

    print(f"\n完成。")


if __name__ == "__main__":
    main()
