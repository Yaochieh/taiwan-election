"""
從中選會下載各選舉的 Excel ZIP 檔。

用法：
  python scripts/download_excel.py               # 下載全部
  python scripts/download_excel.py --subject P0  # 只下載總統
  python scripts/download_excel.py --subject L0,C2
  python scripts/download_excel.py --theme-id 4d83db17c1707e3defae5dc4d4e9c800
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

import requests

BASE_URL = "https://db.cec.gov.tw/static/elections/data/attachments"
INDEX_PATH = Path(__file__).parent.parent / "data" / "elections_index.json"
DOWNLOAD_DIR = Path(__file__).parent.parent / "data" / "downloads"

# 每個 subject_id 要抓的 ZIP 關鍵字（對照 list.json 的 file_desc）
PREFERRED_DESC = {
    "P0": "各投票所得票明細及概況(excel檔",
    "L0": "各投票所得票明細及概況(excel檔",
    "C2": "各投票所得票明細及概況(excel檔",
    "T1": "各投票所得票明細及概況(excel檔",
}

FALLBACK_EXT = ".zip"


def get_list_json(type_id: str, subject_id: str, theme_id: str) -> list[dict]:
    url = f"{BASE_URL}/{type_id}/{subject_id}/{theme_id}/list.json"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def pick_file(file_list: list[dict], subject_id: str) -> dict | None:
    preferred = PREFERRED_DESC.get(subject_id, "excel")
    for f in file_list:
        desc = f.get("file_desc", "").lower()
        name = f.get("file_name", "").lower()
        if preferred.lower() in desc or preferred.lower() in name:
            if name.endswith(".zip"):
                return f
    # fallback: first zip
    for f in file_list:
        if f.get("file_name", "").lower().endswith(".zip"):
            return f
    return None


def download_file(type_id: str, subject_id: str, theme_id: str, file_name: str, out_path: Path):
    encoded = quote(file_name, safe="")
    url = f"{BASE_URL}/{type_id}/{subject_id}/{theme_id}/{encoded}"
    print(f"  下載 {file_name}")
    print(f"    URL: {url}")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
    size_mb = out_path.stat().st_size / 1_048_576
    print(f"    -> {out_path.name} ({size_mb:.1f} MB)")


def load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        print(f"找不到 {INDEX_PATH}，請先執行 build_elections_index.py", file=sys.stderr)
        sys.exit(1)
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def should_process(entry: dict, subject_filter: set[str], theme_filter: set[str]) -> bool:
    if theme_filter:
        return entry["theme_id"] in theme_filter
    if subject_filter:
        return entry["subject_id"] in subject_filter
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", help="逗號分隔的 subject_id，例如 P0,L0")
    parser.add_argument("--theme-id", help="指定單一 theme_id")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="跳過已下載的檔案（預設開啟）")
    args = parser.parse_args()

    subject_filter = set(args.subject.split(",")) if args.subject else set()
    theme_filter = {args.theme_id} if args.theme_id else set()

    elections = load_index()

    # 同一 theme_id 只抓一次
    seen_theme_ids: set[str] = set()
    downloaded = skipped = errors = 0

    for entry in elections:
        if not entry.get("has_data"):
            continue
        if not should_process(entry, subject_filter, theme_filter):
            continue
        theme_id = entry["theme_id"]
        if theme_id in seen_theme_ids:
            continue
        seen_theme_ids.add(theme_id)

        type_id = entry.get("type_id", "ELC")
        subject_id = entry["subject_id"]
        name = entry["name"]

        print(f"\n[{name}] theme_id={theme_id[:8]}...")

        try:
            file_list = get_list_json(type_id, subject_id, theme_id)
        except Exception as e:
            print(f"  list.json 失敗: {e}")
            errors += 1
            continue

        chosen = pick_file(file_list, subject_id)
        if not chosen:
            print(f"  找不到合適的 ZIP 檔，跳過")
            skipped += 1
            continue

        file_name = chosen["file_name"]
        out_path = DOWNLOAD_DIR / type_id / subject_id / theme_id / file_name

        if args.skip_existing and out_path.exists():
            print(f"  已存在，跳過: {out_path.name}")
            skipped += 1
            continue

        try:
            download_file(type_id, subject_id, theme_id, file_name, out_path)
            downloaded += 1
        except Exception as e:
            print(f"  下載失敗: {e}")
            errors += 1

    print(f"\n完成：下載 {downloaded} 個，跳過 {skipped} 個，失敗 {errors} 個")


if __name__ == "__main__":
    main()
