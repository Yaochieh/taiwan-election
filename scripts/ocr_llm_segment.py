"""用 LLM 分段救回「整頁 OCR 但 regex 切不出每人政見」的候選人。

流程：對一個 PDF（一選區）→ OCR 全頁文字 → 給 Claude 全文+候選人名單
→ Claude 回各候選人政見 → 寫入 platforms。

用法：
  python scripts/ocr_llm_segment.py 51    # 2024 區域立委 (election_id=51)

會自動找該 election 缺政見的候選人，對應 PDF（區域+單一選區），逐 PDF 處理。
"""
import json
import os
import re
import sys
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ocr_2024_single_district_legislative import render_pages, ocr_image, JOBS  # noqa
from scripts.ocr_2024_regional_legislative import parse_district_from_path  # noqa

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

REGIONAL_ROOT = ROOT / "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員"

SYSTEM = """你會收到一份台灣立委選舉公報的整頁 OCR 文字（多位候選人混在一起、有雜訊），以及這個選區的候選人名單。

請判斷每位候選人的「政見」內容，整理成乾淨條列。規則：
1. 只取政見，去掉學歷/經歷/個人資料/投票須知/頁碼/亂碼
2. 每位候選人 5-10 條，格式「N. 主題：內容」
3. 找不到某人的政見就回空字串
4. 不要編造原文沒有的內容

輸出 JSON（無 markdown wrap）：
{"候選人姓名": "1. ...\\n2. ...", "另一位": "", ...}"""


def llm_segment(full_text: str, names: list[str]) -> dict:
    msg = client.messages.create(
        model=MODEL, max_tokens=4000, system=SYSTEM,
        messages=[{"role": "user", "content":
            f"候選人名單：{'、'.join(names)}\n\n整頁 OCR 文字：\n{full_text[:18000]}"}],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def collect_pdfs(election_id: int, conn) -> dict:
    """回傳 {pdf_path: [districts]}，只含有缺政見候選人的 PDF。"""
    pdf_districts: dict[Path, set] = {}
    # 區域 PDF
    for pdf in REGIONAL_ROOT.rglob("*.pdf"):
        d = parse_district_from_path(pdf)
        if d:
            pdf_districts.setdefault(pdf, set()).add(d)
    # 單一選區 JOBS
    for district, rel in JOBS:
        pdf_districts.setdefault(ROOT / rel, set()).add(district)
    return pdf_districts


def main():
    election_id = int(sys.argv[1])
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row

    from paddleocr import PaddleOCR
    print("初始化 PaddleOCR…")
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")

    pdf_districts = collect_pdfs(election_id, conn)
    grand = 0
    for pdf, districts in pdf_districts.items():
        if not pdf.exists():
            continue
        # 該 PDF 各選區缺政見的候選人
        missing = {}
        for d in districts:
            rows = conn.execute(
                "SELECT c.candidate_id, c.name FROM election_results er "
                "JOIN candidates c ON er.candidate_id=c.candidate_id "
                "WHERE er.election_id=? AND er.district=?", (election_id, d)).fetchall()
            for r in rows:
                ex = conn.execute("SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=?",
                                  (r["candidate_id"], election_id)).fetchone()
                if not ex:
                    missing[r["name"]] = r["candidate_id"]
        if not missing:
            continue
        print(f"\n=== {pdf.name} 缺 {list(missing)} ===")
        # OCR 全頁
        pages = render_pages(pdf, max_pages=6)
        items = []
        for pi, pp in enumerate(pages):
            for t, bbox in ocr_image(ocr, pp):
                items.append((pi, bbox[1], t))
        items.sort(key=lambda x: (x[0], x[1]))
        full_text = "\n".join(t for _, _, t in items)
        # LLM 分段
        try:
            seg = llm_segment(full_text, list(missing))
        except Exception as e:
            print(f"  ✗ LLM: {e}"); continue
        for name, cid in missing.items():
            text = (seg.get(name) or "").strip()
            if len(text) < 30:
                print(f"  - {name}: LLM 也抽不到 ({len(text)} 字)")
                continue
            tag = "[LLM 潤稿 by Claude haiku 2026-06-18]"
            conn.execute(
                "INSERT INTO platforms (candidate_id, election_id, seq, content, content_raw, note) "
                "VALUES (?, ?, 1, ?, ?, ?)",
                (cid, election_id, text, full_text[:8000], tag))
            conn.execute(
                "INSERT INTO platform_sources (candidate_id, election_id, source_type, local_path, description) "
                "VALUES (?, ?, 'page_ocr', ?, ?)",
                (cid, election_id, str(pdf.relative_to(ROOT)), "公報整頁 OCR + LLM 分段"))
            print(f"  + {name}: {len(text)} 字")
            grand += 1
        conn.commit()
    print(f"\n總計救回 {grand} 條政見")
    conn.close()


if __name__ == "__main__":
    main()
