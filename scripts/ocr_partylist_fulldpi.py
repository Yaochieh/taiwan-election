"""2024不分區整份PDF高DPI重OCR + LLM分段16政黨。
修content_raw太碎/占位的政黨(KMT/DPP等)。

用法：python scripts/ocr_partylist_fulldpi.py
"""
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from scripts.ocr_2024_single_district_legislative import ocr_image  # noqa

DB = ROOT / "data" / "db.sqlite"
OUT_DIR = ROOT / "data" / "bulletin_pages_legislators"
PDF = ROOT / "data/bulletins/01選舉公報/02立法委員/113年第11屆/05全國不分區及僑居國外國民立法委員/全國不分區及僑居國外國民立法委員.pdf"
ENV = ROOT / ".env"
if ENV.exists():
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
from anthropic import Anthropic
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """你會收到台灣不分區立委選舉公報的整份OCR文字(16政黨政見混在一起+候選人個資雜訊),以及政黨名單。
請判斷每個政黨的政見:去雜訊(候選人學歷經歷姓名/亂碼/投票須知),每黨5-12條「N. 主題：內容」,找不到回空字串,不編造。
輸出JSON(無markdown wrap):{"政黨名":"1. ...\\n2. ...", ...}"""


def main():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    # 16政黨
    parties = conn.execute(
        "SELECT c.candidate_id, c.name, p.platform_id, p.content_raw, p.note "
        "FROM candidates c JOIN platforms p ON p.candidate_id=c.candidate_id "
        "WHERE c.election_id=50 AND length(c.name)>3").fetchall()
    all_names = [r["name"] for r in parties]
    # 需修的:仍是手寫(人工潤稿)或占位
    need_fix = {r["name"]: r["platform_id"] for r in parties
                if (r["note"] and "人工潤稿" in r["note"]) or r["content_raw"] == "占位"}
    if not need_fix:
        print("無需修正"); return
    print(f"需修 {list(need_fix)} — 整份PDF dpi=300 重OCR")

    # render 300dpi
    doc = fitz.open(PDF)
    paths = []
    for i in range(doc.page_count):
        out = OUT_DIR / f"hidpi300_partylist_p{i+1}.png"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            doc[i].get_pixmap(matrix=fitz.Matrix(300/72, 300/72)).save(str(out))
        paths.append(out)
    doc.close()

    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")
    items = []
    for pi, pp in enumerate(paths):
        for txt, bbox in ocr_image(ocr, pp):
            items.append((pi, bbox[1], txt))
    items.sort(key=lambda x: (x[0], x[1]))
    full_text = "\n".join(t for _, _, t in items)
    print(f"OCR文字長度: {len(full_text)}字")

    msg = client.messages.create(
        model=MODEL, max_tokens=6000, system=SYSTEM,
        messages=[{"role": "user", "content":
            f"政黨名單：{'、'.join(all_names)}\n\n整份OCR：\n{full_text[:30000]}"}])
    t = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    t = re.sub(r"^```(?:json)?\n?", "", t); t = re.sub(r"\n?```$", "", t)
    try:
        seg = json.loads(t)
    except json.JSONDecodeError:
        print("LLM沒回JSON"); return

    n = 0
    for name, pid in need_fix.items():
        content = (seg.get(name) or "").strip()
        if isinstance(content, dict):
            content = content.get("polished_content", "")
        if len(content) < 30:
            print(f"  - {name}: 仍抽不到({len(content)}字)"); continue
        conn.execute("UPDATE platforms SET content=?, content_raw=?, note=? WHERE platform_id=?",
                     (content, full_text[:8000], "[LLM 潤稿 by Claude haiku 2026-06-19 高DPI]", pid))
        n += 1
        print(f"  ✓ {name}: {len(content)}字")
    conn.commit()
    print(f"\n修正 {n} 個政黨")
    conn.close()


if __name__ == "__main__":
    main()
