"""從總統公報抽履歷(學歷/經歷),存 background_source。標中選會公報。

防腦補機制:
1. 嚴格prompt:只能重排OCR文字,禁止加入任何不在原文的資訊
2. 驗證:輸出的字必須高度出現在OCR原文裡(n-gram重疊),否則判為腦補拒絕

用法：python scripts/extract_president_bio_safe.py
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

ELECTIONS = {
    4: (89, "089年第10任總統副總統.pdf"), 7: (93, "093年第11任總統副總統.pdf"),
    13: (97, "097年第12任總統副總統.pdf"), 30: (101, "101年第13任總統副總統.pdf"),
    39: (105, "105年第14任總統副總統.pdf"), 48: (109, "109年第15任總統副總統.pdf"),
}

SYSTEM = """你是OCR文字整理員。下面是台灣總統選舉公報的OCR文字和候選人名單。

【絕對規則】你只能使用我提供的OCR文字裡「實際出現的字句」來整理每位候選人的學歷/經歷。
嚴禁加入任何OCR文字裡沒有的資訊(出生日期、家庭、未提到的學校職務等)。
你不是在寫傳記,只是把OCR裡屬於某人的學經歷片段抓出來重新排列。
若OCR裡找不到某人的學經歷,回空字串。寧可少也不可加。

輸出JSON(無markdown wrap):{"候選人姓名":"學歷經歷(只能用OCR原文的字)", ...}"""


def render(pdf, dpi=300, max_pages=10):
    doc = fitz.open(pdf); paths = []
    stem = pdf.stem.replace("/", "_")
    for i in range(min(max_pages, doc.page_count)):
        out = OUT_DIR / f"presbio{dpi}_{stem}_p{i+1}.png"
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            doc[i].get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72)).save(str(out))
        paths.append(out)
    doc.close(); return paths


def overlap_ratio(text: str, source: str) -> float:
    """輸出的4-gram有多少比例出現在source裡。低=腦補。"""
    t = re.sub(r"[\s\d。，、：（）()【】「」\.]", "", text)
    s = re.sub(r"[\s\d。，、：（）()【】「」\.]", "", source)
    if len(t) < 4:
        return 0.0
    grams = [t[i:i+4] for i in range(len(t) - 3)]
    if not grams:
        return 0.0
    hit = sum(1 for g in grams if g in s)
    return hit / len(grams)


def main():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000"); conn.row_factory = sqlite3.Row
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")
    grand = rejected = 0
    for eid, (yyy, fname) in ELECTIONS.items():
        pdf = PDF_DIR / fname
        if not pdf.exists():
            continue
        names = [r["name"] for r in conn.execute("SELECT name FROM candidates WHERE election_id=?", (eid,)).fetchall()]
        need = [n for n in names if not conn.execute(
            "SELECT 1 FROM candidates WHERE name=? AND length(COALESCE(background_source,''))>50", (n,)).fetchone()]
        if not need:
            print(f"✓ {yyy+1911}: 都有背景"); continue
        print(f"\n=== {yyy+1911} 缺背景 {need} ===")
        paths = render(pdf); items = []
        for pi, pp in enumerate(paths):
            for txt, bbox in ocr_image(ocr, pp):
                items.append((pi, bbox[1], txt))
        items.sort(key=lambda x: (x[0], x[1]))
        full = "\n".join(t for _, _, t in items)
        msg = client.messages.create(model=MODEL, max_tokens=5000, system=SYSTEM,
            messages=[{"role": "user", "content": f"候選人名單：{'、'.join(names)}\n\nOCR文字：\n{full[:30000]}"}])
        t = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
        t = re.sub(r"^```(?:json)?\n?", "", t); t = re.sub(r"\n?```$", "", t)
        try:
            seg = json.loads(t)
        except json.JSONDecodeError:
            print("  ✗ 沒回JSON"); continue
        for name in need:
            bio = (seg.get(name) or "").strip()
            if isinstance(bio, dict):
                continue
            if len(bio) < 20:
                continue
            ratio = overlap_ratio(bio, full)
            if ratio < 0.80:  # 80%以下=有腦補成分,拒絕
                print(f"  ✗ {name}: 重疊度{ratio:.0%}<80% 疑似腦補,拒絕")
                rejected += 1; continue
            bio_full = f"{bio}\n\n（資料來源：中選會選舉公報 {yyy+1911}年總統副總統選舉）"
            conn.execute("UPDATE candidates SET background_source=? WHERE name=? AND length(COALESCE(background_source,''))<50",
                         (bio_full, name))
            grand += 1
            print(f"  ✓ {name}: {len(bio)}字 (重疊度{ratio:.0%})")
        conn.commit()
    print(f"\n補 {grand} 位 (拒絕腦補 {rejected})")
    conn.close()


if __name__ == "__main__":
    main()
