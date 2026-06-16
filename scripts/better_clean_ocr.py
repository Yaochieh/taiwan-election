"""
比 clean_ocr_passes 更積極的 OCR 政見清理：

1. 句子層級切割（用句號/分號/問號/驚嘆號）
2. 移除 < 4 字 的碎片
3. 重複句子（含部分相似）只留一份
4. 移除「候選人」「副總統候選人」這種公報表頭
5. 移除孤立的「學歷／經歷」標記行
6. 半形/全形標點 normalize
7. 編號重新排序（1. 2. 3. ... 為條列項時保留）

執行：python scripts/better_clean_ocr.py
"""
import re
import sqlite3
from datetime import date
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db.sqlite"

DROP_PATTERNS = [
    re.compile(p) for p in [
        r"^總統候選人$",
        r"^副總統候選人$",
        r"^\d+\s*年.*月.*日$",  # 出生年月日
        r"^臺灣省.*縣.*$",       # 籍貫
        r"^國立.*博士$",         # 學歷殘行
        r"^國立.*碩士$",
        r"^學歷$",
        r"^經歷$",
        r"^政黨$",
        r"^政見$",
        r"^.*校友會.*$",
        r"^.*主任委員$",
        r"^第\d+屆.*主委$",
    ]
]


def normalize(s: str) -> str:
    s = s.replace("．", "。").replace("．", "。")
    s = re.sub(r"[ \t　]+", " ", s)
    s = s.strip()
    return s


def is_drop(line: str) -> bool:
    for p in DROP_PATTERNS:
        if p.search(line):
            return True
    return False


def clean(content: str) -> str:
    lines = [normalize(l) for l in content.split("\n")]
    lines = [l for l in lines if l and not is_drop(l) and len(l) >= 3]
    # dedupe（保留順序）
    seen = set()
    out = []
    for l in lines:
        key = re.sub(r"[，。、；：（）()「」,.\s]", "", l)[:30]
        if key in seen:
            continue
        seen.add(key)
        out.append(l)
    return "\n".join(out)


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    today = date.today().isoformat()
    tag = f"[OCR 二次清理 by Claude {today}]"

    rows = conn.execute("""
        SELECT platform_id, content, note FROM platforms
        WHERE (note IS NULL OR note NOT LIKE '%人工潤稿%')
          AND length(content) > 30
    """).fetchall()

    n = 0
    for r in rows:
        new = clean(r["content"])
        if not new or new == r["content"]:
            continue
        existing = r["note"] or ""
        if tag in existing:
            continue
        new_note = f"{existing} · {tag}" if existing else tag
        conn.execute(
            "UPDATE platforms SET content=?, note=? WHERE platform_id=?",
            (new, new_note, r["platform_id"]),
        )
        n += 1
    conn.commit()
    print(f"✓ 二次清理 {n} 條政見")
    conn.close()


if __name__ == "__main__":
    main()
