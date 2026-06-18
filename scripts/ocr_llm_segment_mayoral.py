"""縣市長公報 LLM 分段 OCR：直轄市長+縣市長 PDF → 縣市 → 候選人 → LLM 分政見。

用法：
  python scripts/ocr_llm_segment_mayoral.py 49 111   # 2022 縣市長(e49,民國111)
  python scripts/ocr_llm_segment_mayoral.py 42 107   # 2018(e42,民國107)
  python scripts/ocr_llm_segment_mayoral.py 33 103   # 2014(e33,民國103)
"""
import json
import os
import re
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ocr_2024_single_district_legislative import render_pages, ocr_image  # noqa
from scripts.ocr_mayoral_by_year import county_from_filename  # noqa

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

SYSTEM = """你會收到一份台灣縣市長選舉公報的整頁 OCR 文字（多位候選人混在一起、有雜訊），以及候選人名單。

請判斷每位候選人的政見，整理乾淨：
1. 只取政見，去掉學歷/經歷/個人資料/投票須知/頁碼/亂碼
2. 每位 5-12 條，格式「N. 主題：內容」
3. 找不到某人的政見就回空字串
4. 不要編造原文沒有的內容

輸出 JSON（無 markdown wrap）：{"候選人姓名": "1. ...\\n2. ...", ...}"""


def llm_segment(full_text: str, names: list[str]) -> dict:
    msg = client.messages.create(
        model=MODEL, max_tokens=4000, system=SYSTEM,
        messages=[{"role": "user", "content":
            f"候選人名單：{'、'.join(names)}\n\n整頁 OCR 文字：\n{full_text[:18000]}"}])
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def main():
    election_id = int(sys.argv[1])
    year = int(sys.argv[2])
    pdf_roots = [
        ROOT / "data/bulletins/01選舉公報/03直轄市長" / f"{year:03d}年",
        ROOT / "data/bulletins/01選舉公報/04縣市長" / f"{year:03d}年",
    ]
    pdfs = []
    for r in pdf_roots:
        if r.exists():
            pdfs.extend(sorted(r.rglob("*.pdf")))
    if not pdfs:
        print(f"找不到 {year} 年公報"); return

    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    from paddleocr import PaddleOCR
    print(f"初始化 PaddleOCR… ({len(pdfs)} PDF, election_id={election_id})")
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")

    grand = 0
    for pdf in pdfs:
        county = county_from_filename(pdf.name)
        if not county:
            print(f"✗ 無法判縣市：{pdf.name}"); continue
        rows = conn.execute(
            "SELECT DISTINCT c.candidate_id, c.name FROM election_results er "
            "JOIN candidates c ON er.candidate_id=c.candidate_id "
            "WHERE er.election_id=? AND er.district=?", (election_id, county)).fetchall()
        if not rows:
            print(f"✗ {county}: DB無候選人"); continue
        name_to_id = {r["name"]: r["candidate_id"] for r in rows}
        missing = {n: cid for n, cid in name_to_id.items()
                   if not conn.execute("SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=?",
                                       (cid, election_id)).fetchone()}
        if not missing:
            print(f"✓ {county}: 已全入庫"); continue
        print(f"\n=== {county} ({pdf.name}) 缺 {list(missing)} ===")
        pages = render_pages(pdf, max_pages=6)
        items = []
        for pi, pp in enumerate(pages):
            for t, bbox in ocr_image(ocr, pp):
                items.append((pi, bbox[1], t))
        items.sort(key=lambda x: (x[0], x[1]))
        full_text = "\n".join(t for _, _, t in items)
        try:
            seg = llm_segment(full_text, list(name_to_id))  # 給全部名單幫助分段
        except Exception as e:
            print(f"  ✗ LLM: {e}"); continue
        for name, cid in missing.items():
            text = (seg.get(name) or "").strip()
            if len(text) < 30:
                print(f"  - {name}: 抽不到 ({len(text)}字)"); continue
            tag = "[LLM 潤稿 by Claude haiku 2026-06-18]"
            conn.execute(
                "INSERT INTO platforms (candidate_id, election_id, seq, content, content_raw, note) "
                "VALUES (?, ?, 1, ?, ?, ?)", (cid, election_id, text, full_text[:8000], tag))
            conn.execute(
                "INSERT INTO platform_sources (candidate_id, election_id, source_type, local_path, description) "
                "VALUES (?, ?, 'page_ocr', ?, ?)",
                (cid, election_id, str(pdf.relative_to(ROOT)), "縣市長公報 OCR + LLM 分段"))
            print(f"  + {name}: {len(text)} 字")
            grand += 1
        conn.commit()
    print(f"\n總計救回 {grand} 條政見")
    conn.close()


if __name__ == "__main__":
    main()
