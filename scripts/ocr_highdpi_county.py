"""高 DPI 重 OCR 救援版面太密的縣市公報（如臺北市 2022 12位候選人）。

用 dpi=300 重新 render + OCR + LLM 分段。

用法：
  python scripts/ocr_highdpi_county.py 49 臺北市 "data/bulletins/01選舉公報/03直轄市長/111年/臺北市市長.pdf"
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

SYSTEM = """你會收到一份台灣縣市長選舉公報的整頁 OCR 文字（多位候選人、有雜訊），以及候選人名單。
請判斷每位候選人的政見，整理乾淨：只取政見去雜訊，每位5-12條「N. 主題：內容」，找不到回空字串，不編造。
輸出 JSON(無markdown wrap)：{"候選人姓名":"1. ...\\n2. ...", ...}"""


def render_highdpi(pdf_path: Path, dpi: int = 300, max_pages: int = 8) -> list[Path]:
    doc = fitz.open(pdf_path)
    paths = []
    stem = pdf_path.stem.replace("/", "_")
    for i in range(min(max_pages, doc.page_count)):
        out = OUT_DIR / f"hidpi{dpi}_{stem}_p{i+1}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
            pix.save(str(out))
        paths.append(out)
    doc.close()
    return paths


def llm_segment(full_text: str, names: list[str]) -> dict:
    msg = client.messages.create(
        model=MODEL, max_tokens=4000, system=SYSTEM,
        messages=[{"role": "user", "content":
            f"候選人名單：{'、'.join(names)}\n\n整頁 OCR：\n{full_text[:20000]}"}])
    t = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    t = re.sub(r"^```(?:json)?\n?", "", t); t = re.sub(r"\n?```$", "", t)
    try:
        seg = json.loads(t)
    except json.JSONDecodeError:
        return {}
    return {k: (v.get("polished_content", "") if isinstance(v, dict) else v)
            for k, v in seg.items()}


def main():
    election_id = int(sys.argv[1])
    county = sys.argv[2]
    pdf = ROOT / sys.argv[3]
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT DISTINCT c.candidate_id, c.name FROM election_results er "
        "JOIN candidates c ON er.candidate_id=c.candidate_id "
        "WHERE er.election_id=? AND er.district=?", (election_id, county)).fetchall()
    name_to_id = {r["name"]: r["candidate_id"] for r in rows}
    missing = {n: cid for n, cid in name_to_id.items()
               if not conn.execute("SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=?",
                                    (cid, election_id)).fetchone()}
    if not missing:
        print(f"{county}: 已全入庫"); return
    print(f"{county} 缺 {list(missing)} — 用 dpi=300 重 OCR")

    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")
    pages = render_highdpi(pdf)
    items = []
    for pi, pp in enumerate(pages):
        for txt, bbox in ocr_image(ocr, pp):
            items.append((pi, bbox[1], txt))
    items.sort(key=lambda x: (x[0], x[1]))
    full_text = "\n".join(t for _, _, t in items)
    print(f"  OCR 文字長度: {len(full_text)} 字")
    seg = llm_segment(full_text, list(name_to_id))
    grand = 0
    for name, cid in missing.items():
        text = (seg.get(name) or "").strip()
        if len(text) < 30:
            print(f"  - {name}: 仍抽不到 ({len(text)}字)"); continue
        conn.execute(
            "INSERT INTO platforms (candidate_id, election_id, seq, content, content_raw, note) "
            "VALUES (?, ?, 1, ?, ?, ?)",
            (cid, election_id, text, full_text[:8000], "[LLM 潤稿 by Claude haiku 2026-06-19 高DPI]"))
        conn.execute(
            "INSERT INTO platform_sources (candidate_id, election_id, source_type, local_path, description) "
            "VALUES (?, ?, 'page_ocr', ?, ?)",
            (cid, election_id, sys.argv[3], "縣市長公報 高DPI OCR + LLM 分段"))
        print(f"  + {name}: {len(text)} 字"); grand += 1
    conn.commit()
    print(f"\n救回 {grand} 條")
    conn.close()


if __name__ == "__main__":
    main()
