"""
從中文維基百科抓政治人物簡介，補進 candidates.background_source。

策略：
- 取曾當選且 background 為空、或 background < 50 字的候選人
- 用 MediaWiki API 查 page extract (summary)
- 同名歧義時優先帶「政治家」「立法委員」「市長」disambiguation
- 存於 candidates.background_source（不覆蓋 background，前端兩處都顯示）
- 標來源 URL

執行：python scripts/fetch_wiki_background.py [--limit 50]
"""
import argparse
import json
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db.sqlite"
API = "https://zh.wikipedia.org/w/api.php"


def fetch_summary(title: str) -> tuple[str, str] | None:
    """回傳 (extract, page_url) 或 None。"""
    params = {
        "action": "query",
        "prop": "extracts|info",
        "exintro": "1",
        "explaintext": "1",
        "exchars": "600",
        "inprop": "url",
        "format": "json",
        "titles": title,
        "redirects": "1",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TaiwanElection/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
    except Exception as e:
        print(f"  [err] {title}: {e}")
        return None
    pages = data.get("query", {}).get("pages", {})
    for _, page in pages.items():
        if "missing" in page:
            return None
        extract = page.get("extract", "").strip()
        purl = page.get("fullurl", "")
        if extract and len(extract) > 40:
            return extract, purl
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # 找最常出現（曾參選多次）且還沒補維基的人
    rows = conn.execute("""
        SELECT name, COUNT(*) as runs,
               MAX(LENGTH(COALESCE(background, ''))) AS bg_len
        FROM candidates
        WHERE name NOT LIKE '%黨%' AND name NOT LIKE '%聯盟%'
        GROUP BY name
        HAVING bg_len < 200 AND runs >= 1
        ORDER BY runs DESC, name
        LIMIT ?
    """, (args.limit,)).fetchall()

    print(f"目標 {len(rows)} 位候選人")
    found = 0
    not_found = 0
    for r in rows:
        name = r["name"]
        # 嘗試三種題名
        titles = [
            f"{name} (政治人物)",
            f"{name}_(政治人物)",
            name,
        ]
        result = None
        for t in titles:
            result = fetch_summary(t)
            time.sleep(0.4)  # rate limit
            if result:
                break
        if not result:
            not_found += 1
            continue
        extract, purl = result
        # 過濾掉明顯不是這個人（內容應包含參選/立委/議員/市長/候選人/政治）
        if not any(k in extract for k in ["政治", "立法委員", "議員", "市長", "候選人", "黨", "選舉"]):
            not_found += 1
            continue
        bg_text = f"{extract}\n\n（資料來源：中文維基百科 {purl}）"
        conn.execute(
            "UPDATE candidates SET background_source=? WHERE name=? AND (background_source IS NULL OR length(background_source) < 50)",
            (bg_text, name),
        )
        conn.commit()
        found += 1
        print(f"  ✓ {name} ({len(extract)} 字)")

    print(f"\n找到 {found}，找不到 {not_found}")
    conn.close()


if __name__ == "__main__":
    main()
