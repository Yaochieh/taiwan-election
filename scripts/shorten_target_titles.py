"""
把 platform_targets 中 title 與 description 完全相同的條目，
title 改寫成「主題：數值 單位」這種短標題，description 保留原文。
"""
import re
import sqlite3
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db.sqlite"


def shorten(text: str, value: float, unit: str) -> str:
    # 去掉前綴編號 "1. 2. ①. (1)"
    t = re.sub(r"^[\s\(（]*[\d①-⑨][\.\)）、:：]?\s*", "", text).strip()
    # 取冒號前的主題
    topic = t.split("：")[0].split(":")[0].split("、")[0].strip()
    if len(topic) > 12:
        topic = topic[:12] + "…"
    # 格式化 value
    if value >= 10000:
        v_str = f"{value / 10000:.1f} 萬"
    elif value == int(value):
        v_str = f"{int(value):,}"
    else:
        v_str = f"{value:g}"
    return f"{topic}：{v_str} {unit or ''}".strip()


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT target_id, title, description, target_value, metric_unit
        FROM platform_targets
        WHERE title = description
          AND target_value IS NOT NULL
    """).fetchall()
    n = 0
    for tid, title, desc, value, unit in rows:
        new_title = shorten(desc, value or 0, unit or "")
        if not new_title or new_title == title:
            continue
        cur.execute(
            "UPDATE platform_targets SET title=? WHERE target_id=?",
            (new_title, tid),
        )
        n += 1
    conn.commit()
    print(f"✓ 改寫 {n} 個 target title")
    conn.close()


if __name__ == "__main__":
    main()
