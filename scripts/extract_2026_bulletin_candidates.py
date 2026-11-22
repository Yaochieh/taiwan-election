"""2026 地方選舉公報 → 候選人基本資料（號次／政黨／學經歷／大頭照）＋政見原文。

範圍：直轄市長(77)、縣市長(78)、直轄市議員(79 區域／80 山原／81 平原)、縣市議員(82)。
來源：中選會公報站 data/bulletins/01選舉公報/0[3-6]*/115年/**.pdf（download_bulletin_office.py）

三階段（各自可重跑）：
  extract  每頁一次 LLM 結構化，結果快取 JSON（不寫 DB）
  verify   每個欄位對該頁原文（PDF 文字層＋PaddleOCR）逐字比對，產出報告
  import   只寫入通過驗證的欄位；照片取 PDF 內嵌原圖（原始解析度，不重新取樣放大）

防腦補：
  - LLM 只負責「切欄位」，所有字串必須能在原文中找到（去空白後子字串比對）；
    找不到的欄位直接丟棄，不寫入
  - 政見原文用 4-gram 重疊 >= 0.9（原文照抄，理應接近 1.0）
  - 姓名：市長／縣長必須在既有登記名冊內；議員必須逐字出現在該頁原文
  - 原文無文字層的頁面（純圖片）改用 PaddleOCR 結果當原文

用法：
  python scripts/extract_2026_bulletin_candidates.py extract [--only 臺北市]
  python scripts/extract_2026_bulletin_candidates.py verify
  python scripts/extract_2026_bulletin_candidates.py import [--dry-run]
"""
import argparse
import collections
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import quote

import fitz

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "db.sqlite"
BUL = ROOT / "data" / "bulletins" / "01選舉公報"
CACHE = BUL / "_extract_115"          # gitignored（data/bulletins/01*/）
OCR_DIR = CACHE / "ocr"
PHOTO_DIR = ROOT / "data" / "candidate_photos"
BASE_URL = "https://bulletin.cec.gov.tw/01%E9%81%B8%E8%88%89%E5%85%AC%E5%A0%B1/"
OFFICES = ["03直轄市長", "04縣市長", "05直轄市議員", "06縣市議員"]
MODEL = "claude-sonnet-5-5"
TODAY = date.today().isoformat()

ENV = ROOT / ".env"
if ENV.exists():
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

COUNTIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹市",
            "嘉義市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "屏東縣",
            "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣"]


# ───────────────────────── 共用 ─────────────────────────

def norm(s: str) -> str:
    """比對用正規化：NFKC、去所有空白、統一常見異體標點。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("台", "臺").replace("塡", "填")
    return re.sub(r"[\s　•·・●◆■□☑⃞]", "", s)


def ngram_overlap(text: str, source: str, n: int = 4) -> float:
    t, s = norm(text), norm(source)
    t = re.sub(r"[，。、：；,.:;（）()「」【】]", "", t)
    s = re.sub(r"[，。、：；,.:;（）()「」【】]", "", s)
    if len(t) < n:
        return 1.0 if t in s else 0.0
    grams = [t[i:i + n] for i in range(len(t) - n + 1)]
    return sum(g in s for g in grams) / len(grams)


def all_pdfs():
    for off in OFFICES:
        for p in sorted((BUL / off / "115年").rglob("*.pdf")):
            yield off, p


def county_of(pdf: Path, office: str) -> str | None:
    for c in COUNTIES:
        if c in pdf.as_posix() or c.replace("臺", "台") in pdf.as_posix():
            return c
    return None


def pdf_url(pdf: Path) -> str:
    rel = pdf.relative_to(BUL).as_posix()
    return BASE_URL + quote(rel)


def page_key(pdf: Path, i: int) -> str:
    h = hashlib.md5(pdf.relative_to(BUL).as_posix().encode()).hexdigest()[:10]
    return f"{h}_p{i + 1}"


def ocr_page(pdf: Path, i: int) -> list[dict]:
    """PaddleOCR 結果（快取）。座標單位：PDF pt。"""
    OCR_DIR.mkdir(parents=True, exist_ok=True)
    js = OCR_DIR / f"{page_key(pdf, i)}.json"
    if js.exists():
        return json.loads(js.read_text())
    global _ocr
    if "_ocr" not in globals():
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, lang="ch")
    doc = fitz.open(pdf)
    dpi = 150
    png = OCR_DIR / f"{page_key(pdf, i)}.png"
    doc[i].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72)).save(str(png))
    items = []
    for page in _ocr.predict(str(png)):
        # PaddleOCR 會把超過 4000px 的圖縮小，rec_polys 對應的是原 png 座標
        for t, poly, s in zip(page["rec_texts"], page["rec_polys"], page["rec_scores"]):
            if s < 0.6:
                continue
            xs = [float(q[0]) * 72 / dpi for q in poly]
            ys = [float(q[1]) * 72 / dpi for q in poly]
            items.append({"t": t, "s": round(float(s), 3),
                          "box": [min(xs), min(ys), max(xs), max(ys)]})
    js.write_text(json.dumps(items, ensure_ascii=False))
    png.unlink(missing_ok=True)
    return items


VISION_BIN = ROOT / "scripts" / "tools" / "vision_ocr"   # swiftc -O scripts/tools/vision_ocr.swift -o ...
VISION_DIR = CACHE / "vision_tiled"


def vision_ocr_pages(pages: list[tuple[Path, int]], dpi: int = 300, nx: int = 3, ny: int = 4, ov: float = 60):
    """macOS Vision OCR（獨立於 PDF 文字層的第二通道），結果快取。
    整頁送 Vision 會漏讀整行（實測），改切 3x4 重疊小塊、300dpi；座標轉回 PDF pt。"""
    import subprocess, tempfile
    VISION_DIR.mkdir(parents=True, exist_ok=True)
    todo = [(p, i) for p, i in pages if not (VISION_DIR / f"{page_key(p, i)}.json").exists()]
    for n, (p, i) in enumerate(todo, 1):
        page = fitz.open(p)[i]
        W, H = page.rect.width, page.rect.height
        with tempfile.TemporaryDirectory() as td:
            tiles = {}
            for a in range(nx):
                for b in range(ny):
                    r = fitz.Rect(a * W / nx - ov, b * H / ny - ov, (a + 1) * W / nx + ov, (b + 1) * H / ny + ov) & page.rect
                    f = f"{td}/t{a}{b}.png"
                    page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=r).save(f)
                    tiles[f] = r
            out = subprocess.run([str(VISION_BIN), *tiles], capture_output=True, text=True, check=True).stdout
        items = []
        for line in out.splitlines():
            d = json.loads(line)
            r = tiles[d["file"]]
            for x in d["items"]:
                bx = x["box"]
                items.append({"t": x["t"], "c": x["c"], "box": [r.x0 + bx[0] * 72 / dpi, r.y0 + bx[1] * 72 / dpi,
                                                               r.x0 + bx[2] * 72 / dpi, r.y0 + bx[3] * 72 / dpi]})
        (VISION_DIR / f"{page_key(p, i)}.json").write_text(json.dumps(items, ensure_ascii=False))
        if n % 20 == 0 or n == len(todo):
            print(f"vision OCR {n}/{len(todo)}", flush=True)


def vision_text(pdf: Path, i: int) -> str:
    js = VISION_DIR / f"{page_key(pdf, i)}.json"
    if not js.exists():
        vision_ocr_pages([(pdf, i)])
    items = json.loads(js.read_text())
    items.sort(key=lambda x: (round(x["box"][0] / 150), x["box"][1]))
    return "\n".join(x["t"] for x in items)


def garble_ratio(t: str) -> float:
    """文字層亂碼比例（字型 ToUnicode 對照壞掉時會出現大量非中文字元）。"""
    t = re.sub(r"\s", "", t)
    if not t:
        return 0.0
    ok = sum(1 for ch in t if 0x4E00 <= ord(ch) <= 0x9FFF or ord(ch) < 0x80
             or 0x3000 <= ord(ch) <= 0x303F or 0xFF00 <= ord(ch) <= 0xFFEF
             or 0x2000 <= ord(ch) <= 0x2BFF or 0x2460 <= ord(ch) <= 0x24FF)
    return 1 - ok / len(t)


def page_source(pdf: Path, i: int) -> tuple[str, str]:
    """回傳 (原文, 種類)。文字層夠用就用文字層；不足則 PaddleOCR。"""
    page = fitz.open(pdf)[i]
    text = page.get_text()
    if len(norm(text)) >= 300 and garble_ratio(text) < 0.05:
        return text, "text_layer"
    items = ocr_page(pdf, i)
    items.sort(key=lambda x: (round(x["box"][0] / 150), x["box"][1]))
    return "\n".join(x["t"] for x in items), "paddleocr"


# ───────────────────────── extract ─────────────────────────

SYSTEM = """你會收到一頁台灣選舉公報的原文（PDF 文字層或 OCR，欄位順序可能錯亂）。
請把頁面上「每一位候選人」的資料切成欄位。

鐵律：
- 每個字串都必須「逐字照抄」原文，不可改字、不可修正錯字、不可補字、不可摘要、不可翻譯
- 原文沒有的欄位填 null；學歷／經歷是逐行照抄的陣列
- 政見 platform：照抄原文整段（保留原本的編號與換行）；若政見是圖片、原文沒有文字，填 null
- 不要把甲候選人的資料放到乙候選人；分不清楚就填 null
- 頁首的選舉名稱／選舉區標題（例如「第3選舉區」「山地原住民選舉區」）照抄到 district_label
- office 照該候選人所屬選舉填，只能是以下之一：
  「直轄市長」「縣市長」「直轄市議員」「縣市議員」「鄉鎮市長」「鄉鎮市民代表」「村里長」
  「山地原住民區長」「山地原住民區民代表」（同一份公報可能合刊多種選舉，要逐人判斷）

只輸出 JSON（不要 markdown）：
{"candidates":[{"office":"直轄市議員","district_label":"…","ballot_no":"1","name":"…","gender":"男",
"birth_date":"…","birthplace":"…","party":"…","education":["…"],"career":["…"],"platform":"…"}]}
沒有候選人（例如投開票所一覽表、投票須知）就回 {"candidates":[]}"""


def llm_extract(source: str, hint: str) -> dict:
    from anthropic import Anthropic
    global _client
    if "_client" not in globals():
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    for attempt in range(3):
        msg = _client.messages.create(
            model=MODEL, max_tokens=16000, system=SYSTEM,
            messages=[{"role": "user", "content": f"檔案：{hint}\n\n原文：\n{source[:60000]}"}])
        if msg.stop_reason == "max_tokens":
            raise RuntimeError("輸出被截斷（max_tokens），此頁需人工拆分")
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if attempt == 2:
                raise
    return {"candidates": []}


def cmd_ocr(args):
    pages = [(pdf, i) for _, pdf in all_pdfs() if not any(k in pdf.name for k in ("投開票所", "投票所"))
             for i in range(fitz.open(pdf).page_count)]
    vision_ocr_pages(pages)


def cmd_extract(args):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    CACHE.mkdir(parents=True, exist_ok=True)
    jobs = []
    for office, pdf in all_pdfs():
        if args.only and args.only not in pdf.as_posix():
            continue
        if any(k in pdf.name for k in ("投開票所", "投票所")):
            continue
        for i in range(fitz.open(pdf).page_count):
            if not (CACHE / f"{page_key(pdf, i)}.json").exists():
                jobs.append((office, pdf, i))
    # 文字層頁先丟給執行緒；需 OCR 的頁在主執行緒逐頁跑（PaddleOCR 非 thread-safe）
    srcs = {}
    text_jobs, ocr_jobs = [], []
    for office, pdf, i in jobs:
        t = fitz.open(pdf)[i].get_text()
        if len(norm(t)) >= 300 and garble_ratio(t) < 0.05:
            srcs[(pdf, i)] = (t, "text_layer"); text_jobs.append((office, pdf, i))
        else:
            ocr_jobs.append((office, pdf, i))
    print(f"文字層 {len(text_jobs)} 頁、需 OCR {len(ocr_jobs)} 頁", flush=True)

    def work(office, pdf, i):
        src, kind = srcs[(pdf, i)]
        if len(norm(src)) < 50:
            res = {"candidates": []}
        else:
            res = llm_extract(src, f"{office}/{pdf.name} 第{i + 1}頁")
        res.update({"pdf": pdf.relative_to(ROOT).as_posix(), "page": i + 1,
                    "office_dir": office, "source_kind": kind, "model": MODEL})
        (CACHE / f"{page_key(pdf, i)}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
        return f"{pdf.relative_to(BUL)} p{i + 1} [{kind}] {len(res['candidates'])} 人"

    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(work, *j): j for j in text_jobs}
        for j in ocr_jobs:
            srcs[(j[1], j[2])] = page_source(j[1], j[2])
            futs[ex.submit(work, *j)] = j
        for f in as_completed(futs):
            try:
                print(f.result(), flush=True)
            except Exception as e:
                o, pdf, i = futs[f]
                print(f"✗ {pdf.relative_to(BUL)} p{i + 1}: {e}", flush=True)


# ───────────────────────── verify ─────────────────────────

ROSTER_DIR = CACHE / "roster"
# 中選會「115年地方公職人員選舉候選人登記名冊」https://web.cec.gov.tw/central/article/64709
ROSTER_FILES = {
    "直轄市長": "bb9a8d7a-9b8a-41ec-8e23-33efd009385a", "縣市長": "370f3bbf-6408-4fdc-b8d8-9b9214913f74",
    "直轄市議員": "ccd7e51a-5fd0-4ea0-a81b-a120cd550c9c", "縣市議員": "9ccb6224-20be-479e-931f-81aa6155f28a",
    "鄉鎮市長": "a7b4f3d3-dad3-4e61-9036-2cd21cf29d92", "鄉鎮市民代表": "437a9da7-eaa7-47b9-9571-789eeb48ed18",
    "村里長": "f1abbda2-229b-4a02-8dfb-58beb3ceca61", "山地原住民區長": "1278f66e-1d15-4ecf-aeeb-9ea5cba61f00",
    "山地原住民區民代表": "f3b665f2-6f0b-485f-a1eb-17d152849317",
}
ROSTER_EXPECT = {"直轄市長": 23, "縣市長": 58, "直轄市議員": 610, "縣市議員": 892, "鄉鎮市長": 465,
                 "鄉鎮市民代表": 3437, "村里長": 14100, "山地原住民區長": 16, "山地原住民區民代表": 94}
ROSTER_PAGE = "https://web.cec.gov.tw/central/article/64709"
# 直轄市議員原住民選舉區（80 山地／81 平地），解析自中選會 115.08.20 公告
# https://web.cec.gov.tw/api/file/45d8e965-f63a-46d5-b636-7d81e47cf4d1.pdf
INDIGENOUS = {
    "臺北市第7選舉區": 81, "臺北市第8選舉區": 80, "新北市第12選舉區": 81, "新北市第13選舉區": 80,
    "桃園市第13選舉區": 81, "桃園市第14選舉區": 80, "臺中市第15選舉區": 81, "臺中市第16選舉區": 80,
    "臺中市第17選舉區": 80, "臺南市第12選舉區": 81, "臺南市第13選舉區": 80, "高雄市第12選舉區": 81,
    "高雄市第13選舉區": 80, "高雄市第14選舉區": 80, "高雄市第15選舉區": 80,
}
TYPE_OF_DIR = {"03直轄市長": "直轄市長", "04縣市長": "縣市長", "05直轄市議員": "直轄市議員", "06縣市議員": "縣市議員"}
TYPE_OF_DIR_REV = {77: "直轄市長", 78: "縣市長", 79: "直轄市議員", 80: "直轄市議員", 81: "直轄市議員", 82: "縣市議員"}


def load_roster() -> dict:
    """{type: [{district,date,name,party,note}]}；人數必須與中選會公告完全一致。"""
    js = ROSTER_DIR / "roster.json"
    if js.exists():
        return json.loads(js.read_text())
    import requests
    ROSTER_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for typ, fid in ROSTER_FILES.items():
        pdf = ROSTER_DIR / f"{fid}.pdf"
        if not pdf.exists():
            pdf.write_bytes(requests.get(f"https://web.cec.gov.tw/api/file/{fid}.pdf", timeout=60).content)
        rows = []
        for page in fitz.open(pdf):
            for t in page.find_tables().tables:
                for r in t.extract():
                    if r[0] == "選舉區" or not r[2]:
                        continue
                    clean = [(x or "").replace("\n", "") for x in r] + [""] * 5
                    rows.append({"district": clean[0], "date": clean[1], "name": clean[2],
                                 "party": clean[3], "note": clean[4]})
        if len(rows) != ROSTER_EXPECT[typ]:
            sys.exit(f"✗ 名冊 {typ} 解析 {len(rows)} 人，公告為 {ROSTER_EXPECT[typ]}")
        out[typ] = rows
    js.write_text(json.dumps(out, ensure_ascii=False))
    return out


def name_key(n: str) -> str:
    """姓名比對鍵：NFKC、去空白與各式間隔點、英文小寫（原住民族名寫法不一，例
    名冊「金凱傑 Ilia．Nangavulan」vs 公報「金凱傑Ilia. Nangavulan」）。"""
    n = unicodedata.normalize("NFKC", n or "").lower()
    return re.sub(r"[\s.．‧·・•‐\-]", "", n)


def roster_index(roster: dict) -> dict:
    idx = {}
    for typ, rows in roster.items():
        for r in rows:
            idx.setdefault((typ, r["district"][:3]), {})[name_key(r["name"])] = r
    return idx


def supported(v: str, primary_n: str, vision_n: str, tol: int = 0) -> str | None:
    """欄位必須同時：逐字出現在主來源，且每個中文字都出現在獨立的 Vision 影像 OCR 中。
    回傳 None = 通過；否則回傳原因。（抓字型 ToUnicode 錯置，例：印「吳秀華」文字層卻是「吳夯華」）"""
    vn = norm(v)
    if not vn:
        return "空白"
    if vn not in primary_n:
        return "不在主來源"
    miss = sorted({ch for ch in vn if "\u4e00" <= ch <= "\u9fff" and ch not in vision_n})
    if len(miss) > tol:
        return f"影像 OCR 找不到字 {''.join(miss)}"
    return None


def layout_tokens(pdf: Path, i: int) -> list[tuple[str, fitz.Rect]]:
    """版面 token：文字層 words（非亂碼頁）＋ Vision OCR 框，座標 PDF pt。"""
    page = fitz.open(pdf)[i]
    toks = []
    if garble_ratio(page.get_text()) < 0.05:
        toks += [(w[4], fitz.Rect(w[:4])) for w in page.get_text("words")]
    js = VISION_DIR / f"{page_key(pdf, i)}.json"
    if js.exists():
        toks += [(x["t"], fitz.Rect(*x["box"])) for x in json.loads(js.read_text())]
    return toks


def ballot_near_name(toks, name: str) -> set[int]:
    """姓名框附近（中心距離 140pt 內）出現的純數字 → 候選號次集合。"""
    cj = "".join(ch for ch in name if "\u4e00" <= ch <= "\u9fff")
    nn = norm(cj if len(cj) >= 2 else name)   # 原住民候選人以漢名定位
    name_boxes = [r for t, r in toks if nn and nn in norm(t)]
    nums = [(int(norm(t)), r) for t, r in toks if norm(t).isdigit() and 0 < int(norm(t)) < 100]
    found = set()
    for nb in name_boxes:
        cx, cy = (nb.x0 + nb.x1) / 2, (nb.y0 + nb.y1) / 2
        best = None
        for v, r in nums:
            d = ((r.x0 + r.x1) / 2 - cx) ** 2 + ((r.y0 + r.y1) / 2 - cy) ** 2
            if d <= 140 ** 2 and (best is None or d < best[0]):
                best = (d, v)
        if best:
            found.add(best[1])
    return found


def verify_record(c: dict, primary_n: str, vision_n: str, ridx: dict, county: str, office_dir: str, toks=None,
                  trusted: bool = False):
    """回傳 (乾淨紀錄 or None, 問題列表)。"""
    probs = []
    want = TYPE_OF_DIR[office_dir]
    name = unicodedata.normalize("NFKC", (c.get("name") or "").strip())
    # 選舉種類以目錄為準；LLM 只需分對「首長／議員」（合刊公報裡的鄉鎮長、代表、村里長略過）
    off = c.get("office") or ""
    is_council_dir = "議員" in want
    if is_council_dir and off not in ("直轄市議員", "縣市議員"):
        return None, []
    if not is_council_dir and off not in ("直轄市長", "縣市長"):
        return None, []
    book = ridx.get((want, county), {})
    k = name_key(name)
    cjk = lambda x: "".join(ch for ch in x if "\u4e00" <= ch <= "\u9fff")
    by_cjk = [r for r in book.values() if cjk(name) and cjk(r["name"]) == cjk(name)]
    if k in book:
        row = book[k]
    elif len(by_cjk) == 1 and len(cjk(name)) >= 2:
        # 原住民候選人：公報只印漢名或族名拼法不同，以漢名唯一對應名冊
        row = by_cjk[0]
    else:
        def ed1(a, b):
            if abs(len(a) - len(b)) > 1:
                return False
            if len(a) == len(b):
                return sum(x != y for x, y in zip(a, b)) == 1
            if len(a) > len(b):
                a, b = b, a
            return any(b[:i] + b[i + 1:] == a for i in range(len(b)))
        ck = cjk(name)
        near = [r for r in book.values() if len(ck) >= 2 and ed1(cjk(r["name"]), ck)]
        party = norm(c.get("party") or "無")
        if len(near) == 1 and (norm(near[0]["name"]) in vision_n or norm(near[0]["party"] or "無") == party):
            why = "影像 OCR 亦同" if norm(near[0]["name"]) in vision_n else "同縣市唯一相近且政黨相符"
            probs.append(f"姓名「{name}」依名冊更正為「{near[0]['name']}」（{why}）")
            row = near[0]
        else:
            return None, [f"姓名「{name}」不在 {county}{want} 名冊，略過"]
    name = row["name"]   # 一律採名冊寫法
    if want == "直轄市議員":
        # 原住民選區依中選會 115.08.20 選舉公告的選舉區劃分（indigenous_districts）
        eid = INDIGENOUS.get(row["district"], 79)
    else:
        eid = {"直轄市長": 77, "縣市長": 78, "縣市議員": 82}[want]
    rec = {"election_id": eid, "district": row["district"], "name": name, "county": county,
           "roster_party": row["party"]}
    bn = norm(str(c.get("ballot_no") or ""))
    near = ballot_near_name(toks or [], name)
    if bn.isdigit() and int(bn) in near:
        rec["ballot_no"] = int(bn)
    else:
        rec["ballot_no"] = None
        if bn:
            probs.append(f"{name} 號次 {bn} 未在姓名旁找到（版面鄰近數字 {sorted(near)}），留空")
    for f in ("gender", "birth_date", "birthplace", "party"):
        v = (c.get(f) or "").strip()
        why = supported(v, primary_n, vision_n) if v else "空白"
        rec[f] = v if why is None else None
        if v and why:
            probs.append(f"{name} {f}「{v}」{why}，丟棄")
    for f in ("education", "career"):
        keep = []
        for line in c.get(f) or []:
            why = supported(line, primary_n, vision_n, tol=1 if trusted and len(norm(line)) >= 8 else 0)
            if why is None:
                keep.append(line.strip())
            elif line:
                probs.append(f"{name} {f}「{line[:24]}」{why}，丟棄")
        rec[f] = keep
    plat = (c.get("platform") or "").strip()
    rec["platform"] = None
    rec["platform_overlap"] = None
    if plat:
        r = ngram_overlap(plat, primary_n)
        pn = norm(plat)
        miss = sorted({ch for ch in pn if "\u4e00" <= ch <= "\u9fff" and ch not in vision_n})
        rec["platform_overlap"] = r
        if r >= 0.9 and len(miss) <= (2 if trusted else 0):
            rec["platform"] = plat
            rec["platform_vision_miss"] = "".join(miss)
        else:
            probs.append(f"{name} 政見未通過（原文重疊 {r:.0%}；影像找不到字 {''.join(miss[:10])}），丟棄")
    return rec, probs


def build_records(conn):
    ridx = roster_index(load_roster())
    recs, problems = [], []
    for js in sorted(CACHE.glob("*_p*.json")):
        d = json.loads(js.read_text())
        if "candidates" not in d:
            continue
        pdf = ROOT / d["pdf"]
        primary, _ = page_source(pdf, d["page"] - 1)
        primary_n, vision_n = norm(primary), norm(vision_text(pdf, d["page"] - 1))
        county = county_of(pdf, d["office_dir"])
        toks = layout_tokens(pdf, d["page"] - 1)
        # 頁面可信度：文字層中文字在影像 OCR 找不到的比例（乾淨頁中位數 0.05%；字型錯置／選委會自行 OCR 的頁偏高）
        cj = [ch for ch in primary_n if "\u4e00" <= ch <= "\u9fff"]
        trusted = d["source_kind"] == "text_layer" and cj and sum(ch not in vision_n for ch in cj) / len(cj) < 0.01
        for c in d["candidates"]:
            rec, probs = verify_record(c, primary_n, vision_n, ridx, county, d["office_dir"], toks, trusted)
            tag = f"{pdf.relative_to(BUL)} p{d['page']}"
            problems += [f"{tag}: {p}" for p in probs]
            if rec:
                rec.update({"pdf": d["pdf"], "page": d["page"], "source_kind": d["source_kind"],
                            "source_url": pdf_url(pdf)})
                recs.append(rec)
    # 同一人在同一場出現多次（跨頁／合刊）→ 合併：欄位取非空者
    merged = {}
    for r in recs:
        k = (r["election_id"], r["district"], r["name"])
        if k not in merged:
            merged[k] = r
        else:
            m = merged[k]
            for f, v in r.items():
                if not m.get(f) and v:
                    m[f] = v
    # 同選區號次重複 → 兩者都留空（寧缺勿假）
    from collections import defaultdict
    seen = defaultdict(list)
    for r in merged.values():
        if r["ballot_no"] is not None:
            seen[(r["election_id"], r["district"], r["ballot_no"])].append(r)
    for k, rs in seen.items():
        if len(rs) > 1:
            for r in rs:
                r["ballot_no"] = None
            problems.append(f"號次重複 {k}: {[r['name'] for r in rs]}，全部留空")
    return list(merged.values()), problems


def cmd_verify(args):
    conn = sqlite3.connect(DB)
    recs, problems = build_records(conn)
    roster = load_roster()
    from collections import Counter, defaultdict
    print(f"通過 {len(recs)} 人；問題 {len(problems)} 則")
    # 1) 名冊有、公報抽不到
    got = {(TYPE_OF_DIR_REV[r["election_id"]], r["district"], name_key(r["name"])) for r in recs}
    missing = [(t, r["district"], r["name"]) for t in TYPE_OF_DIR.values() for r in roster[t]
               if (t, r["district"], name_key(r["name"])) not in got]
    by_t = Counter(m[0] for m in missing)
    for t in TYPE_OF_DIR.values():
        print(f"  {t}: 名冊 {len(roster[t])}、公報通過 {len(roster[t]) - by_t[t]}、缺 {by_t[t]}")
    # 2) 號次：每個選區必須剛好是 1..N 且無重複（N = 公報內通過人數）
    dist = defaultdict(list)
    for r in recs:
        dist[(r["election_id"], r["district"])].append(r["ballot_no"])
    bad_ballot = {k: sorted(v, key=lambda x: (x is None, x)) for k, v in dist.items()
                  if sorted(x for x in v if x is not None) != list(range(1, len(v) + 1))}
    print(f"  號次不連續／缺漏的選區：{len(bad_ballot)}")
    for k, v in list(bad_ballot.items())[:15]:
        print(f"    {k}: {v}")
    rep = CACHE / "verify_report.txt"
    rep.write_text("\n".join(problems + ["", "# 名冊有、公報缺"] + [" ".join(m) for m in missing]
                             + ["", "# 號次異常"] + [f"{k}: {v}" for k, v in bad_ballot.items()]))
    (CACHE / "verified.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1))
    print(f"明細：{rep}")


# ───────────────────────── photos ─────────────────────────

def find_photos(pdf: Path, page_no: int, names: list[str]) -> dict[str, tuple[bytes, int, int]]:
    """候選人大頭照 = 直式小圖（寬 70–230pt、高寬比 1.05–1.6）。
    指派：照片上緣上方 0–140pt、水平距離最近的姓名。
    姓名位置用文字層 search_for，沒有文字層就用 OCR 座標。"""
    doc = fitz.open(pdf)
    page = doc[page_no - 1]
    photos = []
    for img in page.get_images(full=True):
        xref = img[0]
        for r in page.get_image_rects(xref):
            if 70 <= r.width <= 230 and 1.05 <= r.height / max(r.width, 1) <= 1.6:
                photos.append((xref, r))
    pos = {}
    ocr_items = None
    for n in names:
        cj = "".join(ch for ch in n if "\u4e00" <= ch <= "\u9fff")
        if len(cj) >= 2:
            n_search = cj
        else:
            n_search = n
        hits = page.search_for(n_search)
        if not hits and len(n) >= 2:
            # 文字層姓名常被拆成單字加空白
            hits = page.search_for(" ".join(n_search))
        if not hits:
            # 文字層找不到（亂碼／字型錯置）→ 用 Vision OCR 框
            if ocr_items is None:
                ocr_items = layout_tokens(pdf, page_no - 1)
            hits = [r for t, r in ocr_items if norm(n_search) in norm(t) and len(norm(t)) <= len(norm(n_search)) + 4]
        pos[n] = hits
    out = {}
    used = set()
    for n, hits in pos.items():
        best = None
        for h in hits:
            for xref, r in photos:
                dy = r.y0 - h.y0          # 照片在姓名下方（常見版型）
                dx = abs((r.x0 + r.x1) / 2 - (h.x0 + h.x1) / 2)
                if -60 <= dy <= 160 and dx <= 120:
                    score = abs(dy) + dx
                    if best is None or score < best[0]:
                        best = (score, xref, r, h)
        if best and best[1] not in used:
            used.add(best[1])
            pix = fitz.Pixmap(doc, best[1])
            if pix.alpha or pix.n - pix.alpha != 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            # 第 4 項：照片＋姓名框（供目視抽查）；第 5 項：照片框（政見截圖定位用）
            out[n] = (pix.tobytes("png"), pix.width, pix.height, best[2] | best[3], best[2])
    return out


def save_photo(png: bytes, eid: int, cid: int) -> tuple[str, int, int]:
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    # 只縮不放：原圖高於 600px 才縮到 600px，避免放大造成假清晰
    if im.height > 600:
        im = im.resize((round(im.width * 600 / im.height), 600), Image.LANCZOS)
    d = PHOTO_DIR / str(eid)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{cid}.webp"
    im.save(p, "WEBP", quality=88, method=6)
    return p.relative_to(ROOT).as_posix(), im.width, im.height


# ───────────────────────── import ─────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate_bulletin_profiles (
    candidate_id   INTEGER PRIMARY KEY REFERENCES candidates(candidate_id),
    election_id    INTEGER NOT NULL,
    ballot_no      INTEGER,
    gender         TEXT,
    birth_date_raw TEXT,      -- 公報原文（民國）
    birthplace     TEXT,
    party_raw      TEXT,      -- 公報「推薦之政黨」原文
    education      TEXT,      -- JSON array，逐行照抄
    career         TEXT,      -- JSON array，逐行照抄
    photo_width    INTEGER,
    photo_height   INTEGER,
    source_pdf     TEXT NOT NULL,
    source_url     TEXT NOT NULL,
    source_page    INTEGER,
    source_kind    TEXT,      -- text_layer / paddleocr
    extracted_at   TEXT,
    extraction_method TEXT    -- 'llm_segment+verbatim_check'
);
"""


def party_id_of(conn, raw: str | None, create: list):
    if not raw or raw.strip() in ("無", "無黨籍", "無黨籍及未經政黨推薦", "未經政黨推薦"):
        return None
    name = re.sub(r"\s+", "", raw.strip())
    # 比對時忽略空白與台/臺（公報排版常插空白，例「臺灣SoR 無法黨」）
    for pid, pname in conn.execute("SELECT party_id, name FROM parties"):
        if norm(pname) == norm(name):
            return pid
    create.append(name)
    return conn.execute("INSERT INTO parties (name, abbreviation, color_hex) VALUES (?, ?, ?)",
                        (name, name[:3], "#888888")).lastrowid


def cmd_import(args):
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    recs = json.loads((CACHE / "verified.json").read_text())
    new_parties = []
    n_new = n_upd = n_photo = n_plat = 0
    lowres = []
    for r in recs:
        eid = r["election_id"]
        src = f"中選會選舉公報 {r['source_url']}（第{r['page']}頁）"
        # 政黨以中選會登記名冊為準（公報「推薦之政黨」原文另存 party_raw）
        pid = party_id_of(conn, r["roster_party"], new_parties)
        row = conn.execute("SELECT candidate_id FROM candidates WHERE election_id=? AND district=? AND name=?",
                           (eid, r["district"], r["name"])).fetchone()
        if row:
            cid = row[0]
            # 名冊登記者：清登記標記、來源改公報（公報 = 選委會審定後刊登）
            conn.execute("UPDATE candidates SET background=NULL, official_source=?, party_id=? "
                         "WHERE candidate_id=? AND (background IS NULL OR background='[登記中未經審定]')",
                         (src, pid, cid))
            n_upd += 1
        else:
            if eid in (77, 78):
                continue  # verify 已確保在名冊，理論上不會發生
            cid = conn.execute(
                "INSERT INTO candidates (name, party_id, election_id, district, official_source) "
                "VALUES (?, ?, ?, ?, ?)", (r["name"], pid, eid, r["district"], src)).lastrowid
            n_new += 1
        pw = ph = None
        photos = find_photos(ROOT / r["pdf"], r["page"], [r["name"]])
        if r["name"] in photos:
            png, w, h = photos[r["name"]][:3]
            if not args.dry_run:
                path, pw, ph = save_photo(png, eid, cid)
                conn.execute("UPDATE candidates SET photo_path=? WHERE candidate_id=?", (path, cid))
            else:
                pw, ph = w, h
            n_photo += 1
            if w < 200:
                lowres.append(f"{r['district']} {r['name']} {w}x{h}")
        conn.execute(
            "INSERT OR REPLACE INTO candidate_bulletin_profiles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, eid, r["ballot_no"], r["gender"], r["birth_date"], r["birthplace"], r["party"],
             json.dumps(r["education"], ensure_ascii=False), json.dumps(r["career"], ensure_ascii=False),
             pw, ph, r["pdf"], r["source_url"], r["page"], r["source_kind"], TODAY,
             "llm_segment+verbatim_check"))
        if r["platform"] and not conn.execute(
                "SELECT 1 FROM platforms WHERE candidate_id=? AND election_id=?", (cid, eid)).fetchone():
            conn.execute(
                "INSERT INTO platforms (candidate_id, election_id, seq, content, content_raw, source_url, note) "
                "VALUES (?, ?, 1, ?, ?, ?, ?)",
                (cid, eid, r["platform"], r["platform"], r["source_url"],
                 f"[公報原文照抄 {TODAY}；LLM 只切欄位，原文 4-gram 重疊 {r['platform_overlap']:.0%}"
                 + (f"；影像 OCR 未讀到「{r['platform_vision_miss']}」" if r.get("platform_vision_miss") else "") + "]"))
            conn.execute(
                "INSERT INTO platform_sources (candidate_id, election_id, source_type, url, local_path, description) "
                "VALUES (?, ?, 'bulletin_text', ?, ?, ?)",
                (cid, eid, r["source_url"], r["pdf"], f"115年選舉公報第{r['page']}頁 原文"))
            n_plat += 1
    # 名冊登記但公報沒有 → 列出，不刪（人工確認是否退選）
    left = conn.execute("SELECT election_id, district, name FROM candidates "
                        "WHERE election_id IN (77,78) AND background='[登記中未經審定]'").fetchall()
    for l in left:
        print(f"  ⚠ 名冊有、公報未見（保留標記，待人工確認）：e{l[0]} {l[1]} {l[2]}")
    print(f"新增 {n_new}、更新 {n_upd}、照片 {n_photo}、政見 {n_plat}；新政黨 {sorted(set(new_parties))}")
    if lowres:
        print(f"低解析照片（原圖寬 < 200px，無法更清楚）{len(lowres)} 張，例：{lowres[:5]}")
    if args.dry_run:
        conn.rollback(); print("(dry-run，未寫入)")
    else:
        conn.commit()


# ── 地方層級（無選舉公報）：直接由中選會登記名冊匯入，姓名以影像 OCR 雙通道核對 ──
LOCAL_ELECTIONS = {
    "村里長": {"name": "115年村里長選舉", "type": "village_chief",
               "desc": "村（里）長；名單取自中選會候選人登記名冊（115-08-31～09-04 登記）"},
}
REG_MARK = "[登記中未經審定]"
# 先找「區」（直轄市與省轄市；避免「平鎮區」在「鎮」被切開），沒有才找鄉鎮市
_DIST_RE = (re.compile(r"^(.{2}[市縣])(.+?區)(.+[村里])$"), re.compile(r"^(.{2}[市縣])(.+?[鄉鎮市])(.+[村里])$"))


class _Dist:
    @staticmethod
    def match(s):
        for r in _DIST_RE:
            m = r.match(s)
            if m:
                return m
        return None


_DIST = _Dist()


# Vision 常把異體字讀成另一寫法（實測：德→徳、黃→黄、橫→横、啓→啟、煥→焕）。
# 只在「比對」時視為相同，寫入一律用名冊原字；其他不一致一律人工看 PDF 原頁。
_VARIANTS = str.maketrans({"徳": "德", "黄": "黃", "横": "橫", "啟": "啓", "焕": "煥"})


def _vkey(s: str) -> str:
    return name_key(norm(s)).translate(_VARIANTS)


def _vhit(s: str, page_key_text: str) -> bool:
    k = _vkey(s)
    if k in page_key_text:
        return True
    # 原住民族名：漢字與羅馬拼音 Vision 常拆成兩段
    han = re.sub(r"[^\u4e00-\u9fff]", "", k)
    lat = re.sub(r"[^a-z]", "", k)
    return bool(han and lat) and han in page_key_text and lat in re.sub(r"[^a-z]", "", page_key_text)


def roster_rows_by_page(typ: str):
    """與 load_roster 同一解析法，但保留頁碼與儲存格座標（核對影像 OCR 要用）。"""
    pdf = ROSTER_DIR / f"{ROSTER_FILES[typ]}.pdf"
    out = []
    for i, page in enumerate(fitz.open(pdf)):
        for t in page.find_tables().tables:
            for r, row in zip(t.extract(), t.rows):
                if r[0] == "選舉區" or not r[2]:
                    continue
                c = [(x or "").replace("\n", "") for x in r] + [""] * 5
                out.append({"district": c[0], "name": c[2], "party": c[3], "note": c[4], "page": i,
                            "cell_district": row.cells[0], "cell_name": row.cells[2]})
    return pdf, out


def _vision_in_cell(items, cell) -> str:
    """儲存格內的影像 OCR 文字（依 y 排序；切塊重疊造成的重複行去掉）。"""
    x0, y0, x1, y1 = cell
    got, seen = [], set()
    for it in sorted(items, key=lambda d: (d["box"][1], d["box"][0])):
        cx, cy = (it["box"][0] + it["box"][2]) / 2, (it["box"][1] + it["box"][3]) / 2
        if x0 - 2 <= cx <= x1 + 2 and y0 - 2 <= cy <= y1 + 2 and it["t"] not in seen:
            seen.add(it["t"]); got.append(it["t"])
    return _vkey("".join(got))


def cmd_roster_import(args):
    typ = args.only or "村里長"
    if typ not in LOCAL_ELECTIONS:
        sys.exit(f"✗ {typ} 不在 LOCAL_ELECTIONS（有公報的類型請走 extract/verify/import）")
    meta = LOCAL_ELECTIONS[typ]
    pdf, rows = roster_rows_by_page(typ)
    ref = load_roster()[typ]
    if len(rows) != ROSTER_EXPECT[typ] or [(r["district"], r["name"]) for r in rows] != \
            [(r["district"], r["name"]) for r in ref]:
        sys.exit(f"✗ 逐頁解析 {len(rows)} 筆與名冊快取不一致")
    pages = sorted({r["page"] for r in rows})
    vision_ocr_pages([(pdf, i) for i in pages])
    vitems = {i: json.loads((VISION_DIR / f"{page_key(pdf, i)}.json").read_text()) for i in pages}
    ok, bad = [], []
    for r in rows:
        m = _DIST.match(r["district"])
        village = m.group(3) if m else r["district"]
        # 同一列的儲存格內比對（不是整頁找得到就算）；儲存格會斷行，Vision 拆成多段再接回
        hit_n = _vhit(r["name"], _vision_in_cell(vitems[r["page"]], r.pop("cell_name")))
        hit_v = _vhit(village, _vision_in_cell(vitems[r["page"]], r.pop("cell_district")))
        (ok if hit_n and hit_v else bad).append({**r, "name_ok": hit_n, "village_ok": hit_v})
    print(f"{typ}：{len(rows)} 筆，影像 OCR 姓名與村里名皆對上 {len(ok)}，未對上 {len(bad)}")
    review = CACHE / f"roster_review_{typ}.json"
    review.write_text(json.dumps(bad, ensure_ascii=False, indent=1))
    # 人工目視確認過的（看過 PDF 原頁截圖，名冊文字正確）才放行
    confirmed_f = CACHE / f"roster_confirmed_{typ}.json"
    confirmed = {(c["district"], c["name"]) for c in json.loads(confirmed_f.read_text())} \
        if confirmed_f.exists() else set()
    # 造字（Unicode 私用區）或村里名缺字：原頁也印不出該字，無法確認，一律不收
    pua = lambda t: any(0xE000 <= ord(ch) <= 0xF8FF for ch in t)
    unsure = [{**r, "name_ok": False, "village_ok": False} for r in ok
              if pua(r["name"] + r["district"]) or not _DIST.match(r["district"])]
    bad += unsure
    held = [b for b in bad if (b["district"], b["name"]) not in confirmed
            or pua(b["name"] + b["district"]) or not _DIST.match(b["district"])]
    if held:
        print(f"  ⚠ {len(held)} 筆未經雙通道或人工確認，本次不匯入；清單見 {review}")
    if args.dry_run:
        return
    conn = sqlite3.connect(DB)
    e = conn.execute("SELECT election_id FROM elections WHERE name=?", (meta["name"],)).fetchone()
    eid = e[0] if e else conn.execute(
        "INSERT INTO elections (name, type, date, status, description) VALUES (?, ?, '2026-11-28', 'upcoming', ?)",
        (meta["name"], meta["type"], meta["desc"])).lastrowid
    url = f"https://web.cec.gov.tw/api/file/{ROSTER_FILES[typ]}.pdf"
    new_parties, n_new = [], 0
    held_keys = {(b["district"], b["name"]) for b in held}
    for r in rows:
        if (r["district"], r["name"]) in held_keys:
            continue
        if conn.execute("SELECT 1 FROM candidates WHERE election_id=? AND district=? AND name=?",
                        (eid, r["district"], r["name"])).fetchone():
            continue
        conn.execute(
            "INSERT INTO candidates (name, party_id, election_id, district, background, official_source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (r["name"], party_id_of(conn, r["party"], new_parties), eid, r["district"], REG_MARK,
             f"中選會 115年地方公職人員選舉候選人登記名冊 {ROSTER_PAGE} {url}（第{r['page'] + 1}頁）"))
        n_new += 1
    conn.commit()
    print(f"✓ e{eid} 新增 {n_new}；新政黨 {sorted(set(new_parties))}")


# ── 議員選舉區範圍與名額（中選會 115.08.20 公告） ──
ANNOUNCE_URL = "https://web.cec.gov.tw/api/file/45d8e965-f63a-46d5-b636-7d81e47cf4d1.pdf"
# 公告表格依此順序列出各縣市；縣市欄為直排字，桃園、高雄抽不到文字，改用順序＋名冊選區數核對
ANNOUNCE_ORDER = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "新竹縣", "苗栗縣", "彰化縣",
                  "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣",
                  "連江縣", "基隆市", "新竹市", "嘉義市"]
MUNI = {"臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市"}

DISTRICT_SCHEMA = """
CREATE TABLE IF NOT EXISTS election_districts (
    election_id INTEGER NOT NULL REFERENCES elections(election_id),
    district    TEXT NOT NULL,
    area        TEXT NOT NULL,     -- 選舉區範圍，公告原文
    seats       INTEGER,           -- 應選名額
    women_seats INTEGER,           -- 其中婦女保障名額
    source_url  TEXT NOT NULL,
    PRIMARY KEY (election_id, district)
);
"""


def cmd_districts(args):
    pdf = ROSTER_DIR / "announce_0820.pdf"
    rows = []
    doc = fitz.open(pdf)
    for pno in range(1, len(doc)):
        for t in doc[pno].find_tables().tables:
            for r in t.extract():
                c = [(x or "").replace("\n", "").replace(" ", "") for x in r]
                for k, x in enumerate(c):
                    if re.fullmatch(r"第\d+選舉區", x):
                        rest = [y for y in c[k + 1:] if y]
                        if rest and rest[0].endswith(("、", "之")):
                            # 跨頁斷掉的儲存格：接續文字在下一頁開頭（跳過直排縣市名的單字行）
                            cont = []
                            for line in doc[pno + 1].get_text().splitlines():
                                line = line.strip()
                                if re.fullmatch(r"第\d+選舉區.*", line) or re.fullmatch(r"[\d,]+", line) and cont:
                                    break
                                if len(line) >= 2 and not line.isdigit():
                                    cont.append(line)
                            rest[0] += "".join(cont)
                        rows.append((x, rest))
                        break
    groups = []
    for x, rest in rows:
        if x == "第1選舉區":
            groups.append([])
        groups[-1].append((x, rest))
    R = load_roster()
    if len(groups) != len(ANNOUNCE_ORDER):
        sys.exit(f"✗ 公告解析出 {len(groups)} 個縣市，預期 {len(ANNOUNCE_ORDER)}")
    out = []
    for county, g in zip(ANNOUNCE_ORDER, groups):
        typ = "直轄市議員" if county in MUNI else "縣市議員"
        n_roster = len({r["district"] for r in R[typ] if r["district"].startswith(county)})
        if n_roster != len(g):
            sys.exit(f"✗ {county} 公告 {len(g)} 區、名冊 {n_roster} 區，順序對應有誤")
        for i, (x, rest) in enumerate(g, 1):
            if x != f"第{i}選舉區" or len(rest) < 2 or not rest[1].isdigit():
                sys.exit(f"✗ {county}{x} 解析異常：{rest}")
            district = f"{county}{x}"
            eid = INDIGENOUS.get(district, 79) if county in MUNI else 82
            out.append((eid, district, rest[0], int(rest[1]),
                        int(rest[2]) if len(rest) > 2 and rest[2].isdigit() else None))
    print(f"{len(out)} 個選舉區；例：{out[0]}")
    if args.dry_run:
        return
    conn = sqlite3.connect(DB)
    conn.executescript(DISTRICT_SCHEMA)
    conn.executemany(
        "INSERT OR REPLACE INTO election_districts VALUES (?, ?, ?, ?, ?, ?)",
        [(*o, ANNOUNCE_URL) for o in out])
    conn.commit()


# ── 圖片版政見：公報上印成圖片（或文字抽不出）的政見，截圖＋影像 OCR 文字 ──
PLAT_HEADERS = {"政見", "政見內容", "政見：", "政見:", "政見欄"}


def platform_rects(conn) -> tuple[dict, collections.Counter]:
    """沒有文字政見的 2026 候選人 → 公報上「政見」格的位置。
    定位：候選人照片所在表格裡、照片右側最近的「政見」標題，取其正下方儲存格。
    任何一條檢查不過就不截（寧缺勿錯）：
      框內不能有別人的照片、不能有第二個政見標題、水平範圍不能涵蓋別人照片所在欄，
      下緣不超過該候選人左欄最後一行（具結聲明）。"""
    todo = conn.execute("""
        SELECT c.candidate_id, c.name, c.election_id, bp.source_pdf, bp.source_page, bp.source_url
        FROM candidates c JOIN candidate_bulletin_profiles bp USING (candidate_id)
        WHERE c.election_id BETWEEN 77 AND 82
          AND NOT EXISTS (SELECT 1 FROM platforms p WHERE p.candidate_id = c.candidate_id)""").fetchall()
    bypage = collections.defaultdict(list)
    for r in todo:
        bypage[(r[3], r[4])].append(r)
    res, why = {}, collections.Counter()
    for (pdfrel, pg), cands in bypage.items():
        pdf = ROOT / pdfrel
        page = fitz.open(pdf)[pg - 1]
        allnames = [r[0] for r in conn.execute(
            "SELECT c.name FROM candidates c JOIN candidate_bulletin_profiles bp USING (candidate_id) "
            "WHERE bp.source_pdf = ? AND bp.source_page = ?", (pdfrel, pg))]
        ph = find_photos(pdf, pg, allnames)
        toks = layout_tokens(pdf, pg - 1)
        tables = page.find_tables().tables
        heads = [r for t, r in toks if norm(t) in PLAT_HEADERS]
        ctr = lambda r: fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        for cid, name, eid, _, _, url in cands:
            if name not in ph:
                why["no_photo_anchor"] += 1; continue
            a = ph[name][4]
            tb = [t for t in tables if fitz.Rect(t.bbox).contains(ctr(a))]
            if not tb:
                why["no_table"] += 1; continue
            T = min(tb, key=lambda t: fitz.Rect(t.bbox).get_area())   # 頁框也會被偵測成大表，取最內層
            hs = [h for h in heads if fitz.Rect(T.bbox).contains(ctr(h)) and h.x0 > a.x0]
            if not hs:
                why["no_header"] += 1; continue
            h = min(hs, key=lambda h: max(0, h.x0 - a.x1) + abs(ctr(h).y - ctr(a).y) * 0.5)
            cells = [fitz.Rect(x) for x in T.cells if x]
            hcell = [x for x in cells if x.contains(ctr(h))]
            if not hcell:
                why["no_header_cell"] += 1; continue
            hcell = min(hcell, key=lambda r: r.get_area())
            below = [x for x in cells if x.y0 >= hcell.y1 - 2 and x.x0 < hcell.x1 - 5 and x.x1 > hcell.x0 + 5]
            if not below:
                why["no_cell_below"] += 1; continue
            u = fitz.Rect(hcell.x0, hcell.y1, hcell.x1, max(x.y1 for x in below))
            foot = [r.y1 for t, r in toks if ("國籍" in t or "護照" in t)
                    and a.x0 - 90 < ctr(r).x < a.x1 + 90 and r.y0 > a.y1]
            foot = [f for f in foot if f > u.y0 + 40]   # 政見格在左欄下方的版型：具結聲明在框上方，不夾
            if foot:
                # 同頁下方的候選人也有具結聲明：只取最近那組（與最近一行相距 120pt 內）
                first = min(foot)
                u.y1 = min(u.y1, max(f for f in foot if f - first <= 120) + 25)
            if u.height < 40:
                why["too_small"] += 1; continue
            others = [v[4] for n2, v in ph.items() if n2 != name]
            if any(u.intersects(o) and (u & o).get_area() > 0.3 * o.get_area() for o in others):
                why["contains_other_photo"] += 1; continue
            if any(u.x0 < ctr(o).x < u.x1 for o in others):
                why["spans_other_column"] += 1; continue
            if any(u.contains(ctr(hh)) for hh in heads):
                why["contains_other_header"] += 1; continue
            res[cid] = {"pdf": pdfrel, "page": pg, "rect": list(u), "name": name, "eid": eid, "url": url}
            why["ok"] += 1
    return res, why


def cmd_platform_images(args):
    from PIL import Image
    fitz.TOOLS.mupdf_display_errors(False)
    conn = sqlite3.connect(DB)
    res, why = platform_rects(conn)
    print(f"政見格定位：{dict(why)}")
    if args.dry_run:
        return
    out_dir = ROOT / "data" / "bulletin_images"
    n = 0
    for cid, v in res.items():
        pdf = ROOT / v["pdf"]
        page = fitz.open(pdf)[v["page"] - 1]
        r = fitz.Rect(v["rect"])
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=r)
        im = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        if im.width > 1100:
            im = im.resize((1100, round(im.height * 1100 / im.width)), Image.LANCZOS)
        rel = Path("data/bulletin_images") / str(v["eid"]) / f"{cid}_1.webp"
        (ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
        im.save(ROOT / rel, "WEBP", quality=78, method=6)
        # 影像 OCR 文字：同頁 Vision 結果中落在政見格內者，依行（y）再依 x 排序
        vision_ocr_pages([(pdf, v["page"] - 1)])
        items = json.loads((VISION_DIR / f"{page_key(pdf, v['page'] - 1)}.json").read_text())
        inside, seen = [], set()
        for it in items:
            b = fitz.Rect(it["box"])
            c = fitz.Point((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)
            key = (it["t"], round(b.x0 / 6), round(b.y0 / 6))   # 切塊重疊造成的重複
            if r.contains(c) and key not in seen:
                seen.add(key); inside.append(it)
        inside.sort(key=lambda it: (round(it["box"][1] / 10), it["box"][0]))
        ocr = "\n".join(it["t"] for it in inside)
        conn.execute("DELETE FROM platform_sources WHERE candidate_id = ? AND election_id = ? "
                     "AND source_type = 'image_platform'", (cid, v["eid"]))
        conn.execute(
            "INSERT INTO platform_sources (candidate_id, election_id, source_type, url, local_path, "
            "description, fetched_at, ocr_text) VALUES (?, ?, 'image_platform', ?, ?, ?, ?, ?)",
            (cid, v["eid"], v["url"], rel.as_posix(),
             f"候選人公報政見（圖片版，自中選會選舉公報第{v['page']}頁擷取）", TODAY, ocr or None))
        n += 1
    conn.commit()
    print(f"✓ 政見截圖 {n} 張")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ocr", "extract", "verify", "import", "roster-import", "districts", "platform-images"])
    ap.add_argument("--only")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    {"ocr": cmd_ocr, "extract": cmd_extract, "verify": cmd_verify, "import": cmd_import,
     "roster-import": cmd_roster_import, "districts": cmd_districts,
     "platform-images": cmd_platform_images}[a.cmd](a)


if __name__ == "__main__":
    main()
