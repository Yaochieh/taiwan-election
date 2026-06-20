"""從縣市長公報安全抽取候選人履歷(學歷/經歷),存background_source。標中選會公報。
防腦補:嚴格prompt + 80%重疊度驗證(輸出的字必須在OCR原文裡)。

用法：python scripts/extract_mayoral_bio_safe.py 49 111   # 2022縣市長(e49,民國111)
只補當選者(現任/近任縣市長,高價值)。
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

SYSTEM = """你是OCR文字整理員。下面是台灣縣市長選舉公報的OCR文字和候選人名單。
【絕對規則】只能用OCR文字裡實際出現的字句整理每位候選人的學歷/經歷。
嚴禁加入OCR沒有的資訊(出生日期/家庭/未提到的學校職務)。不是寫傳記,只是抓OCR裡屬於某人的學經歷片段重排。
找不到回空字串。寧可少不可加。
輸出JSON(無markdown wrap):{"候選人姓名":"【學歷】...【經歷】...", ...}"""


def render(pdf, dpi=300, max_pages=8):
    doc = fitz.open(pdf); paths = []
    stem = pdf.stem.replace("/", "_")
    for i in range(min(max_pages, doc.page_count)):
        out = OUT_DIR / f"biodpi{dpi}_{stem}_p{i+1}.png"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            doc[i].get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72)).save(str(out))
        paths.append(out)
    doc.close(); return paths


def overlap_ratio(text, source):
    t = re.sub(r"[\s\d。，、：（）()【】「」\.]", "", text)
    s = re.sub(r"[\s\d。，、：（）()【】「」\.]", "", source)
    if len(t) < 4:
        return 0.0
    grams = [t[i:i+4] for i in range(len(t)-3)]
    return sum(1 for g in grams if g in s) / len(grams) if grams else 0.0


def main():
    election_id = int(sys.argv[1]); year = int(sys.argv[2])
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000"); conn.row_factory = sqlite3.Row
    pdfs = []
    for sub in ["03直轄市長", "04縣市長"]:
        r = ROOT / "data/bulletins/01選舉公報" / sub / f"{year:03d}年"
        if r.exists():
            pdfs.extend(sorted(r.rglob("*.pdf")))
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")
    grand = rejected = 0
    for pdf in pdfs:
        county = county_from_filename(pdf.name)
        if not county:
            continue
        rows = conn.execute(
            "SELECT DISTINCT c.candidate_id, c.name, er.elected FROM election_results er "
            "JOIN candidates c ON er.candidate_id=c.candidate_id "
            "WHERE er.election_id=? AND er.district=?", (election_id, county)).fetchall()
        names = [r["name"] for r in rows]
        # 只補當選者且還沒背景
        need = [r["name"] for r in rows if r["elected"] == 1 and not conn.execute(
            "SELECT 1 FROM candidates WHERE name=? AND length(COALESCE(background_source,''))>50", (r["name"],)).fetchone()]
        if not need:
            continue
        print(f"\n=== {county} 補當選者履歷 {need} ===")
        paths = render(pdf)
        items = []
        for pi, pp in enumerate(paths):
            for txt, bbox in ocr_image(ocr, pp):
                items.append((pi, bbox[1], txt))
        items.sort(key=lambda x: (x[0], x[1]))
        full = "\n".join(t for _, _, t in items)
        msg = client.messages.create(model=MODEL, max_tokens=4000, system=SYSTEM,
            messages=[{"role": "user", "content": f"候選人名單：{'、'.join(names)}\n\nOCR：\n{full[:20000]}"}])
        t = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
        t = re.sub(r"^```(?:json)?\n?", "", t); t = re.sub(r"\n?```$", "", t)
        try:
            seg = json.loads(t)
        except json.JSONDecodeError:
            print("  ✗ 沒回JSON"); continue
        for name in need:
            bio = (seg.get(name) or "").strip()
            if isinstance(bio, dict) or len(bio) < 20:
                continue
            ratio = overlap_ratio(bio, full)
            if ratio < 0.80:
                print(f"  ✗ {name}: 重疊{ratio:.0%}<80% 拒絕"); rejected += 1; continue
            bio_full = f"{bio}\n\n（資料來源：中選會選舉公報 {year+1911}年縣市長選舉）"
            conn.execute("UPDATE candidates SET background_source=? WHERE name=? AND length(COALESCE(background_source,''))<50",
                         (bio_full, name))
            grand += 1; print(f"  ✓ {name}: {len(bio)}字 (重疊{ratio:.0%})")
        conn.commit()
    print(f"\n補 {grand} 位縣市長履歷 (拒絕腦補 {rejected})")
    conn.close()


if __name__ == "__main__":
    main()
