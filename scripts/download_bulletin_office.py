"""下載指定職位+年份的公報 PDF（扁平 BFS，跳過全站 walk）。

用法：
  python scripts/download_bulletin_office.py 04縣市長 111 107 103
  python scripts/download_bulletin_office.py 03直轄市長 111
"""
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote

import requests

BASE = "https://bulletin.cec.gov.tw"
ROOT = Path(__file__).parent.parent


def fetch(dir_path: str) -> str:
    r = requests.get(f"{BASE}/?dir={quote(dir_path)}", timeout=30)
    r.raise_for_status()
    return r.text


def parse(html: str):
    import re
    dirs = [unquote(d) for d in re.findall(r'href="\?dir=([^"]+)"', html)]
    pdfs = [unquote(p) for p in re.findall(r'href="([^"]+\.pdf)"', html, re.I)]
    return dirs, pdfs


def collect(office: str, year: int) -> list[str]:
    base = f"01選舉公報/{office}/{year:03d}年"
    queue = [base]
    seen = set()
    pdfs = []
    while queue:
        d = queue.pop(0)
        if d in seen:
            continue
        seen.add(d)
        try:
            dirs, found = parse(fetch(d))
        except Exception as e:
            print(f"  skip {d}: {e}")
            continue
        for sub in dirs:
            if sub.startswith(base) and sub not in seen:
                queue.append(sub)
        pdfs.extend(found)
        time.sleep(0.12)
    return pdfs


def main():
    office = sys.argv[1]
    years = [int(y) for y in sys.argv[2:]]
    total = 0
    for year in years:
        pdfs = collect(office, year)
        print(f"\n[{office} {year}年] {len(pdfs)} 個 PDF")
        for i, p in enumerate(pdfs, 1):
            target = ROOT / "data" / "bulletins" / p
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.stat().st_size > 1000:
                continue
            try:
                r = requests.get(f"{BASE}/{quote(p)}", timeout=90, stream=True)
                r.raise_for_status()
                with open(target, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                total += 1
                print(f"  [{year} {i}/{len(pdfs)}] ✓ {target.name} ({target.stat().st_size//1024}KB)")
                time.sleep(0.3)
            except Exception as e:
                print(f"  ✗ {p}: {e}")
    print(f"\n總共下載 {total} 個新 PDF")


if __name__ == "__main__":
    main()
