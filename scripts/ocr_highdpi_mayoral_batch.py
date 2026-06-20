"""批次高DPI(300)補縣市長缺政見的當選者(版面太密200DPI抽不到的)。

用法：python scripts/ocr_highdpi_mayoral_batch.py 42 107   # 2018縣市長(e42,民國107)
"""
import json
import os
import re
import sys
import sqlite3
from pathlib import Path

import fitz

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from scripts.ocr_2024_single_district_legislative import ocr_image  # noqa
from scripts.ocr_mayoral_by_year import county_from_filename  # noqa

DB = ROOT / "data" / "db.sqlite"
OUT_DIR = ROOT / "data" / "bulletin_pages_legislators"
ENV = ROOT / ".env"
if ENV.exists():
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
from anthropic import Anthropic
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-haiku-4-5-20251001"

SYSTEM = """你會收到台灣縣市長選舉公報的整頁OCR文字(多位候選人+雜訊)和候選人名單。
判斷每位候選人的政見,去雜訊(學歷經歷/姓名/亂碼),每位5-12條「N. 主題：內容」,找不到回空字串,不編造。
輸出JSON(無markdown wrap):{"候選人姓名":"1. ...\\n2. ...", ...}"""


def render(pdf, dpi=300, max_pages=8):
    doc = fitz.open(pdf); paths = []
    stem = pdf.stem.replace("/", "_")
    for i in range(min(max_pages, doc.page_count)):
        out = OUT_DIR / f"hidpi{dpi}_m_{stem}_p{i+1}.png"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            doc[i].get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72)).save(str(out))
        paths.append(out)
    doc.close(); return paths


def main():
    election_id = int(sys.argv[1]); year = int(sys.argv[2])
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000"); conn.row_factory = sqlite3.Row
    pdf_roots = [
        ROOT / "data/bulletins/01選舉公報/03直轄市長" / f"{year:03d}年",
        ROOT / "data/bulletins/01選舉公報/04縣市長" / f"{year:03d}年",
    ]
    pdfs = []
    for r in pdf_roots:
        if r.exists():
            pdfs.extend(sorted(r.rglob("*.pdf")))

    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")
    grand = 0
    for pdf in pdfs:
        county = county_from_filename(pdf.name)
        if not county:
            continue
        rows = conn.execute(
            "SELECT DISTINCT c.candidate_id, c.name FROM election_results er "
            "JOIN candidates c ON er.candidate_id=c.candidate_id "
            "WHERE er.election_id=? AND er.district=?", (election_id, county)).fetchall()
        name_to_id = {r["name"]: r["candidate_id"] for r in rows}
        missing = {n: cid for n, cid in name_to_id.items()
                   if not conn.execute("SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=?",
                                       (cid, election_id)).fetchone()}
        # 只處理「有缺當選者」的縣市
        won_missing = [n for n, cid in missing.items()
                       if conn.execute("SELECT 1 FROM election_results WHERE candidate_id=? AND election_id=? AND elected=1",
                                       (cid, election_id)).fetchone()]
        if not won_missing:
            continue
        print(f"\n=== {county} ({pdf.name}) 缺當選者 {won_missing} ===")
        paths = render(pdf)
        items = []
        for pi, pp in enumerate(paths):
            for txt, bbox in ocr_image(ocr, pp):
                items.append((pi, bbox[1], txt))
        items.sort(key=lambda x: (x[0], x[1]))
        full = "\n".join(t for _, _, t in items)
        print(f"  OCR {len(full)}字")
        msg = client.messages.create(model=MODEL, max_tokens=4000, system=SYSTEM,
            messages=[{"role": "user", "content": f"候選人名單：{'、'.join(name_to_id)}\n\nOCR：\n{full[:20000]}"}])
        t = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
        t = re.sub(r"^```(?:json)?\n?", "", t); t = re.sub(r"\n?```$", "", t)
        try:
            seg = json.loads(t)
        except json.JSONDecodeError:
            print("  ✗ 沒回JSON"); continue
        for name, cid in missing.items():
            content = seg.get(name) or ""
            if isinstance(content, dict):
                content = content.get("polished_content", "")
            content = content.strip()
            if len(content) < 30:
                print(f"  - {name}: 抽不到({len(content)}字)"); continue
            conn.execute(
                "INSERT INTO platforms (candidate_id, election_id, seq, content, content_raw, note) "
                "VALUES (?, ?, 1, ?, ?, ?)",
                (cid, election_id, content, full[:8000], "[LLM 潤稿 by Claude haiku 2026-06-20 高DPI]"))
            conn.execute(
                "INSERT INTO platform_sources (candidate_id, election_id, source_type, local_path, description) "
                "VALUES (?, ?, 'page_ocr', ?, ?)",
                (cid, election_id, str(pdf.relative_to(ROOT)), "縣市長公報 高DPI OCR + LLM 分段"))
            print(f"  + {name}: {len(content)}字"); grand += 1
        conn.commit()
    print(f"\n救回 {grand} 條")
    conn.close()


if __name__ == "__main__":
    main()
