"""
爬 bulletin.cec.gov.tw 全站，下載所有選舉公報 PDF。

目錄結構：
  01選舉公報/
    01總統副總統/
    02立法委員/
    03直轄市長/  ← 重點
    04縣市長/
    05直轄市議員/
    06縣市議員/
    ...

每個職位下分年份（民國年），每年下有縣市別 PDF。

用法：
  python scripts/download_bulletins.py                # 全部
  python scripts/download_bulletins.py --filter 直轄市長 # 只下載直轄市長
  python scripts/download_bulletins.py --dry-run      # 只列檔案不下載
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote

import requests

BASE = "https://bulletin.cec.gov.tw"
ROOT_DIR = "01選舉公報"
OUT_DIR = Path(__file__).parent.parent / "data" / "bulletins"
INDEX_PATH = OUT_DIR / "_index.json"


def fetch_dir(dir_path: str) -> str:
    """抓某個目錄的 HTML 列表頁。"""
    url = f"{BASE}/?dir={quote(dir_path)}"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.text


def parse_listing(html: str) -> dict:
    """從列表頁解析子目錄與 PDF 連結。"""
    sub_dirs = []
    for m in re.finditer(r'href="\?dir=([^"]+)"', html):
        sub_dirs.append(unquote(m.group(1)))
    pdfs = []
    for m in re.finditer(r'<a\s+href="([^"]+\.pdf)"[^>]*>\s*([^<]+?)\s*<', html, re.IGNORECASE):
        href, title = m.group(1), m.group(2).strip()
        pdfs.append({"path": href, "title": title})
    return {"sub_dirs": sub_dirs, "pdfs": pdfs}


def walk(start_dir: str, filter_keyword: str | None = None) -> list[dict]:
    """遞迴走訪目錄樹，回傳所有 PDF 紀錄。"""
    visited = set()
    queue = [start_dir]
    results = []

    while queue:
        d = queue.pop(0)
        if d in visited:
            continue
        visited.add(d)

        if filter_keyword and filter_keyword not in d and d != start_dir:
            # 仍然要進去頂層職位看，但如果不符合就略過
            depth = d.count("/")
            if depth >= 2:
                continue

        try:
            html = fetch_dir(d)
        except requests.HTTPError as e:
            print(f"  跳過 {d}: HTTP {e.response.status_code}", file=sys.stderr)
            continue

        listing = parse_listing(html)

        for sub in listing["sub_dirs"]:
            if sub not in visited and sub.startswith(start_dir):
                queue.append(sub)

        for pdf in listing["pdfs"]:
            results.append({
                "dir": d,
                "filename": pdf["path"].rsplit("/", 1)[-1],
                "title": pdf["title"],
                "url": f"{BASE}/{quote(pdf['path'])}",
                "path": pdf["path"],
            })
        time.sleep(0.2)  # 禮貌間隔

    return results


def parse_metadata(path: str) -> dict:
    """從目錄路徑抽取分類、年份等 metadata。
    範例：01選舉公報/03直轄市長/099年/01臺北市市長.pdf  ← 4 parts
    或   01選舉公報/01總統副總統/085年第9任總統副總統.pdf ← 3 parts (檔名含年份)
    """
    parts = path.split("/")
    meta = {"category": None, "office": None, "minguo_year": None, "ad_year": None, "region": None}
    if len(parts) >= 1:
        meta["category"] = re.sub(r"^\d+", "", parts[0])
    if len(parts) >= 2:
        meta["office"] = re.sub(r"^\d+", "", parts[1])

    # 從整個路徑找民國年（最後一段或倒數第二段）
    for p in reversed(parts):
        m = re.search(r"(\d{2,3})年", p)
        if m:
            meta["minguo_year"] = int(m.group(1))
            meta["ad_year"] = meta["minguo_year"] + 1911
            break

    # 區域：檔名去除前綴數字、副職位、.pdf
    fname = parts[-1].rsplit(".pdf", 1)[0]
    fname = re.sub(r"^\d+", "", fname)
    # 移除「市長」「議員」等職位字串
    region = re.sub(r"(?:市長|議員|長|選舉)$", "", fname)
    region = re.sub(r"(?:第\d+任[總統副]+)", "", region).strip()
    meta["region"] = region or fname
    return meta


def download(record: dict, out_dir: Path) -> bool:
    """下載一個 PDF 檔。回傳 True 表示新下載，False 表示已存在。"""
    local = out_dir / record["path"]
    if local.exists() and local.stat().st_size > 0:
        return False
    local.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(record["url"], timeout=60)
    r.raise_for_status()
    local.write_bytes(r.content)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter", help="只下載含此關鍵字的子目錄（如「直轄市長」）")
    parser.add_argument("--dry-run", action="store_true", help="只列檔案不下載")
    args = parser.parse_args()

    print(f"📂 起始掃描：{ROOT_DIR}/{args.filter or '*'}")
    records = walk(ROOT_DIR, args.filter)
    print(f"   找到 {len(records)} 個 PDF")

    # 補上 metadata
    for r in records:
        r["metadata"] = parse_metadata(r["path"])

    if args.dry_run:
        for r in records[:20]:
            m = r["metadata"]
            print(f"  {m['ad_year']} {m['office']} / {m['region']}  ({r['filename']})")
        if len(records) > 20:
            print(f"  ... +{len(records)-20} 筆")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    new_count = 0
    skip_count = 0
    fail_count = 0

    for i, r in enumerate(records, 1):
        try:
            if download(r, OUT_DIR):
                new_count += 1
                tag = "↓"
            else:
                skip_count += 1
                tag = "·"
        except Exception as e:
            fail_count += 1
            tag = "✗"
            print(f"  ✗ {r['path']}: {e}", file=sys.stderr)
            continue

        if i % 10 == 0 or i == len(records):
            print(f"  {tag} [{i}/{len(records)}] {r['path']}")
        time.sleep(0.15)

    # 寫索引
    INDEX_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print(f"✓ 完成：新下載 {new_count}，已存在 {skip_count}，失敗 {fail_count}")
    print(f"✓ 索引：{INDEX_PATH}")


if __name__ == "__main__":
    main()
