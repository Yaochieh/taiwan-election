"""清理 content 被存成 raw JSON({"polished_content":...}) 的政見。
抽出 polished_content；若為「無有效政見內容」則刪除該 platform。

用法：python scripts/clean_json_contaminated.py [election_id]
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db.sqlite"


def extract(content: str) -> str | None:
    t = content.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"```\s*$", "", t)
    # 取第一個 JSON 物件
    m = re.search(r"\{.*?\"polished_content\".*?\}", t, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return (obj.get("polished_content") or "").strip()
    except Exception:
        # 退而求其次：regex 抓 polished_content 值
        m2 = re.search(r'"polished_content"\s*:\s*"((?:[^"\\]|\\.)*)"', t, re.S)
        if m2:
            return m2.group(1).replace("\\n", "\n").strip()
    return None


def main():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    where = ""
    params = []
    if len(sys.argv) > 1:
        where = "AND election_id=?"
        params = [int(sys.argv[1])]
    rows = conn.execute(
        f"SELECT platform_id, candidate_id, election_id, content FROM platforms "
        f"WHERE content LIKE '%polished_content%' {where}", params
    ).fetchall()
    fixed = deleted = 0
    for r in rows:
        clean = extract(r["content"])
        if clean is None:
            continue
        if not clean or "無有效政見" in clean or len(clean) < 20:
            conn.execute("DELETE FROM platforms WHERE platform_id=?", (r["platform_id"],))
            deleted += 1
        else:
            conn.execute("UPDATE platforms SET content=? WHERE platform_id=?",
                         (clean, r["platform_id"]))
            fixed += 1
    conn.commit()
    print(f"✓ 修正 {fixed}，刪除無效 {deleted}（共 {len(rows)} 筆污染）")
    conn.close()


if __name__ == "__main__":
    main()
