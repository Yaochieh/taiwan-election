"""
從中選會 API 抓取所有選舉的 theme_id 索引，存為 data/elections_index.json。
"""

import json
import requests
from pathlib import Path

ENDPOINTS = {
    "P0": "https://db.cec.gov.tw/static/elections/list/ELC_P0.json",
    "L0": "https://db.cec.gov.tw/static/elections/list/ELC_L0.json",
    "C2": "https://db.cec.gov.tw/static/elections/list/ELC_C2.json",
    "T1": "https://db.cec.gov.tw/static/elections/list/ELC_T1.json",
}

OUTPUT = Path(__file__).parent.parent / "data" / "elections_index.json"


def fetch_elections() -> list[dict]:
    results = []
    for subject_id, url in ENDPOINTS.items():
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        elections = resp.json()
        for e in elections:
            results.append({
                "name": e.get("electionName") or e.get("name"),
                "vote_date": e.get("electionDate") or e.get("vote_date"),
                "type_id": e.get("typeId") or e.get("type_id", "ELC"),
                "subject_id": e.get("subjectId") or e.get("subject_id", subject_id),
                "subject_name": e.get("subjectName") or e.get("subject_name"),
                "legislator_type_id": e.get("legislatorTypeId") or e.get("legislator_type_id"),
                "legislator_desc": e.get("legislatorDesc") or e.get("legislator_desc"),
                "theme_id": e.get("themeId") or e.get("theme_id"),
                "theme_group": e.get("themeGroup") or e.get("theme_group"),
                "session": e.get("session"),
                "has_data": e.get("hasData") or e.get("has_data", True),
            })
        print(f"  {subject_id}: {len(elections)} 筆")
    return results


def main():
    print("正在從中選會 API 抓取選舉索引...")
    elections = fetch_elections()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(elections, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成，共 {len(elections)} 筆，存至 {OUTPUT}")


if __name__ == "__main__":
    main()
