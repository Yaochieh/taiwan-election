"""
2024 第 11 屆區域立委公報 OCR：
73 個選舉區 × 約 2-6 位候選人 = ~309 候選人。

每個 PDF 對應一個選區。檔名包含縣市與選區編號，需 fuzzy 映射到 DB 中的
district 欄位 (例：'臺北市第01選區')。

執行：
  python scripts/ocr_2024_regional_legislative.py
"""
import re
import sqlite3
import sys
from pathlib import Path
import glob

import fitz

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "db.sqlite"
OUT_DIR = ROOT / "data" / "bulletin_pages_legislators"
PDF_ROOT = ROOT / "data/bulletins/01選舉公報/02立法委員/113年第11屆/02區域立法委員"

ELECTION_ID = 51  # 2024 區域


def parse_district_from_path(pdf_path: Path) -> str | None:
    """從 PDF 路徑+檔名推斷 DB district 名稱。
    例：
      .../02臺北市/第3選舉區/臺北市立委第3選舉區.pdf → 臺北市第03選區
      .../11南投縣/南投縣立委第1.2選舉區.pdf → 多選區（特殊）
    """
    parts = pdf_path.parts
    # 找縣市名
    county = None
    for part in parts:
        m = re.match(r"^\d{2}(.+)$", part)
        if m and ("縣" in m.group(1) or "市" in m.group(1)):
            county = m.group(1)
            break
    if not county:
        return None
    county = county.replace("台", "臺")

    # 找選舉區號
    fname = pdf_path.name
    parent = pdf_path.parent.name
    m = re.search(r"第(\d+)選舉區", parent + " " + fname)
    if m:
        num = int(m.group(1))
        return f"{county}第{num:02d}選區"
    # fallback: 從檔名找
    m = re.search(r"第(\d+(?:[.\-]\d+)?)選[舉區]", fname)
    if m:
        nums = re.split(r"[.\-]", m.group(1))
        if len(nums) == 1:
            return f"{county}第{int(nums[0]):02d}選區"
    return None


def render_pages(pdf_path: Path, max_pages: int = 4, dpi: int = 200) -> list[Path]:
    doc = fitz.open(pdf_path)
    paths = []
    safe_stem = pdf_path.stem.replace("/", "_")
    for i in range(min(max_pages, doc.page_count)):
        out = OUT_DIR / f"{safe_stem}_{pdf_path.parent.name}_p{i+1}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = doc[i].get_pixmap(matrix=mat)
            pix.save(str(out))
        paths.append(out)
    doc.close()
    return paths


def ocr_image(ocr, image_path: Path):
    result = ocr.predict(str(image_path))
    out = []
    for page in result:
        if isinstance(page, dict):
            texts = page.get("rec_texts", [])
            polys = page.get("rec_polys", [])
            scores = page.get("rec_scores", [])
            for t, poly, s in zip(texts, polys, scores):
                if s and s > 0.5:
                    xs = [p[0] for p in poly]
                    ys = [p[1] for p in poly]
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    out.append((t.strip(), bbox))
    return out


def extract_per_candidate(all_items: list, names: list[str]) -> dict[str, str]:
    name_pos = {}
    for n in names:
        for t, _, _, abs_y in all_items:
            if t.strip() == n:
                name_pos[n] = abs_y
                break
        if n in name_pos:
            continue
        # prefix match (處理含拼音的名字)
        if len(n) >= 2:
            prefix = n[:2]
            for t, _, _, abs_y in all_items:
                tt = t.strip()
                if tt.startswith(prefix) and len(tt) <= len(n) + 8:
                    name_pos[n] = abs_y
                    break
    if not name_pos:
        return {n: "" for n in names}
    sorted_names = sorted(name_pos.items(), key=lambda x: x[1])
    max_y = max(item[3] for item in all_items) if all_items else 1e9
    result = {}
    for i, (n, y_start) in enumerate(sorted_names):
        y_end = sorted_names[i + 1][1] - 5 if i + 1 < len(sorted_names) else max_y
        in_range = [
            (abs_y, t)
            for t, _, _, abs_y in all_items
            if y_start - 5 < abs_y < y_end and len(t) >= 4
        ]
        in_range.sort()
        result[n] = "\n".join(t for _, t in in_range)
    for n in names:
        result.setdefault(n, "")
    return result


def main():
    print("初始化 PaddleOCR…")
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    pdf_files = sorted(PDF_ROOT.rglob("*.pdf"))
    print(f"📋 找到 {len(pdf_files)} 個區域立委公報 PDF")

    grand = 0
    skipped_no_dist = 0
    for pdf in pdf_files:
        district = parse_district_from_path(pdf)
        if not district:
            print(f"  ✗ 無法解析 district：{pdf.name}")
            skipped_no_dist += 1
            continue

        # 撈該選區候選人
        rows = conn.execute(
            "SELECT DISTINCT c.candidate_id, c.name "
            "FROM election_results er JOIN candidates c ON er.candidate_id=c.candidate_id "
            "WHERE er.election_id=? AND er.district=?",
            (ELECTION_ID, district),
        ).fetchall()
        names = [r["name"] for r in rows]
        name_to_id = {r["name"]: r["candidate_id"] for r in rows}
        # 跳過全已存在的選區
        already = [
            r["name"] for r in rows
            if conn.execute(
                "SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=?",
                (r["candidate_id"], ELECTION_ID),
            ).fetchone()
        ]
        missing = [n for n in names if n not in already]
        if not missing:
            print(f"  ✓ {district}: 已全部入庫，跳過")
            continue
        if not names:
            print(f"  ✗ {district}: DB 無候選人")
            continue
        print(f"\n=== {district} ({pdf.name}) ===")
        print(f"  缺政見：{missing}")

        # 渲染 + OCR
        page_paths = render_pages(pdf)
        all_items = []
        for page_idx, page_path in enumerate(page_paths):
            items = ocr_image(ocr, page_path)
            for t, bbox in items:
                abs_y = page_idx * 10000 + (bbox[1] + bbox[3]) / 2
                all_items.append((t, bbox, page_idx, abs_y))

        politics = extract_per_candidate(all_items, names)
        imported = 0
        for n in missing:
            text = (politics.get(n) or "").strip()
            cid = name_to_id[n]
            if not text or len(text) < 30:
                print(f"  - {n}: 過短 ({len(text)} 字)")
                continue
            conn.execute(
                "INSERT INTO platforms (candidate_id, election_id, seq, title, content) "
                "VALUES (?, ?, 1, NULL, ?)",
                (cid, ELECTION_ID, text),
            )
            conn.execute(
                "INSERT INTO platform_sources "
                "(candidate_id, election_id, source_type, local_path, description) "
                "VALUES (?, ?, 'page_ocr', ?, ?)",
                (cid, ELECTION_ID, str(pdf.relative_to(ROOT)), "公報整頁 OCR"),
            )
            print(f"  + {n}: {len(text)} 字")
            imported += 1
        conn.commit()
        grand += imported

    print(f"\n總計新增 {grand} 條政見，跳過 {skipped_no_dist} 個無法解析 district 的 PDF")
    conn.close()


if __name__ == "__main__":
    main()
