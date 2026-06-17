"""針對單一屆立委 (民國年) 直接下載所有 PDF，跳過全站 walk。

用法：
  python scripts/download_legislative_pdfs.py 109   # 2020 第10屆
  python scripts/download_legislative_pdfs.py 105   # 2016 第9屆
"""
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote

import requests

BASE = "https://bulletin.cec.gov.tw"
ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "bulletins" / "01選舉公報" / "02立法委員"


def fetch(dir_path: str) -> str:
    r = requests.get(f"{BASE}/?dir={quote(dir_path)}", timeout=30)
    r.raise_for_status()
    return r.text


def parse(html: str) -> dict:
    dirs = re.findall(r'href="\?dir=([^"]+)"', html)
    pdfs = re.findall(r'href="([^"]+\.pdf)"', html, re.IGNORECASE)
    return {
        "dirs": [unquote(d) for d in dirs],
        "pdfs": [unquote(p) for p in pdfs],
    }


def walk_year(year: int) -> list[str]:
    """從 02立法委員/YYY年第X屆 開始 BFS"""
    # 找 entry point
    start = fetch("01選舉公報/02立法委員")
    entries = [d for d in parse(start)["dirs"]
               if f"{year:03d}年" in d and "02立法委員" in d]
    if not entries:
        print(f"找不到 {year} 年的目錄"); return []
    base = entries[0]
    print(f"起點：{base}")
    queue = [base]
    visited = set()
    pdfs = []
    while queue:
        d = queue.pop(0)
        if d in visited: continue
        visited.add(d)
        try:
            html = fetch(d)
        except Exception as e:
            print(f"  skip {d}: {e}"); continue
        p = parse(html)
        for sub in p["dirs"]:
            if sub.startswith(base) and sub not in visited:
                queue.append(sub)
        for pdf in p["pdfs"]:
            pdfs.append(pdf)
        time.sleep(0.15)
        print(f"  ... visited {len(visited)} dirs, found {len(pdfs)} PDFs", end="\r")
    print()
    return pdfs


def download(year: int):
    pdfs = walk_year(year)
    print(f"\n共 {len(pdfs)} 個 PDF")
    for i, p in enumerate(pdfs, 1):
        target = ROOT / "data" / "bulletins" / p
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            continue
        try:
            url = f"{BASE}/{quote(p)}"
            r = requests.get(url, timeout=60, stream=True)
            r.raise_for_status()
            with open(target, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            print(f"  [{i}/{len(pdfs)}] ✓ {target.name} ({target.stat().st_size//1024}KB)")
            time.sleep(0.3)
        except Exception as e:
            print(f"  [{i}/{len(pdfs)}] ✗ {p}: {e}")


if __name__ == "__main__":
    year = int(sys.argv[1])
    download(year)
