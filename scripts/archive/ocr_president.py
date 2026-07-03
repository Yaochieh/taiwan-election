"""總統選舉公報 LLM 分段 OCR(高DPI)。從真實公報還原各屆總統候選人政見。

用法：python scripts/ocr_president.py
自動處理所有缺政見的總統選舉(1996-2020)。
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
PDF_DIR = ROOT / "data/bulletins/01選舉公報/01總統副總統"
ENV = ROOT / ".env"
if ENV.exists():
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
from anthropic import Anthropic
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-haiku-4-5-20251001"

# election_id → (民國年數字, PDF檔名)
ELECTIONS = {
    64: (85, "085年第9任總統副總統.pdf"),
    4:  (89, "089年第10任總統副總統.pdf"),
    7:  (93, "093年第11任總統副總統.pdf"),
    13: (97, "097年第12任總統副總統.pdf"),
    30: (101, "101年第13任總統副總統.pdf"),
    39: (105, "105年第14任總統副總統.pdf"),
    48: (109, "109年第15任總統副總統.pdf"),
}

SYSTEM = """你會收到台灣總統副總統選舉公報的整份OCR文字(多組正副總統候選人政見混在一起+個資雜訊),以及候選人名單(含正副總統)。
請判斷每位候選人的政見:去雜訊(學歷經歷/亂碼/投票須知),每位5-12條「N. 主題：內容」。
注意:政見通常以「正副總統一組」共用,請把該組政見同時填給正總統和副總統。找不到回空字串,不編造。
輸出JSON(無markdown wrap):{"候選人姓名":"1. ...\\n2. ...", ...}"""


def render(pdf: Path, dpi=300, max_pages=10):
    doc = fitz.open(pdf)
    paths = []
    stem = pdf.stem.replace("/", "_")
    for i in range(min(max_pages, doc.page_count)):
        out = OUT_DIR / f"pres{dpi}_{stem}_p{i+1}.png"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            doc[i].get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72)).save(str(out))
        paths.append(out)
    doc.close()
    return paths


def main():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")

    grand = 0
    for eid, (yyy, fname) in ELECTIONS.items():
        pdf = PDF_DIR / fname
        if not pdf.exists():
            print(f"✗ {fname} 不存在"); continue
        rows = conn.execute(
            "SELECT candidate_id, name FROM candidates WHERE election_id=?", (eid,)).fetchall()
        name_to_id = {r["name"]: r["candidate_id"] for r in rows}
        missing = {n: cid for n, cid in name_to_id.items()
                   if not conn.execute("SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=?",
                                       (cid, eid)).fetchone()}
        if not missing:
            print(f"✓ {yyy+1911}年: 已全入庫"); continue
        print(f"\n=== {yyy+1911}年總統(e{eid}) 缺 {list(missing)} ===")
        paths = render(pdf)
        items = []
        for pi, pp in enumerate(paths):
            for txt, bbox in ocr_image(ocr, pp):
                items.append((pi, bbox[1], txt))
        items.sort(key=lambda x: (x[0], x[1]))
        full_text = "\n".join(t for _, _, t in items)
        print(f"  OCR {len(full_text)}字")
        msg = client.messages.create(
            model=MODEL, max_tokens=6000, system=SYSTEM,
            messages=[{"role": "user", "content":
                f"候選人名單：{'、'.join(name_to_id)}\n\n整份OCR：\n{full_text[:30000]}"}])
        t = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
        t = re.sub(r"^```(?:json)?\n?", "", t); t = re.sub(r"\n?```$", "", t)
        try:
            seg = json.loads(t)
        except json.JSONDecodeError:
            print("  ✗ LLM沒回JSON"); continue
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
                (cid, eid, content, full_text[:8000], "[LLM 潤稿 by Claude haiku 2026-06-19 總統高DPI]"))
            conn.execute(
                "INSERT INTO platform_sources (candidate_id, election_id, source_type, local_path, description) "
                "VALUES (?, ?, 'page_ocr', ?, ?)",
                (cid, eid, str(pdf.relative_to(ROOT)), "總統公報 高DPI OCR + LLM 分段"))
            print(f"  + {name}: {len(content)}字"); grand += 1
        conn.commit()
    print(f"\n總計救回 {grand} 條總統政見")
    conn.close()


if __name__ == "__main__":
    main()
