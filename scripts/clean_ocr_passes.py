"""
程式化 OCR 政見清理。

- 拿掉表頭殘字（性別／出生年月日／黨籍／登記號碼）
- 拿掉穿插的英文 slogan（TAIWAN, PARTY, STATEBUILDING）
- 把連續換行壓成段落
- 拿掉前綴/後綴的政黨名重複行
- 標記 note='[OCR 清理 by Claude YYYY-MM-DD]'，保留原文於 platforms.note 標籤
"""
import re
import sqlite3
from datetime import date
from pathlib import Path

DB = Path(__file__).parent.parent / "data" / "db.sqlite"

NOISE_PATTERNS = [
    r"性別[:：]\s*[男女]",
    r"出生年月日[:：][^\n]*",
    r"出生地[:：][^\n]*",
    r"黨籍[:：][^\n]*",
    r"登記號碼[:：][^\n]*",
    r"^\d+\s*$",
]

ENGLISH_SLOGAN = re.compile(
    r"\b(TAIWAN|PARTY|STATEBUILDING|FORMOSA|REPUBLIC)\b",
    re.IGNORECASE,
)


def clean_text(raw: str, party_name: str | None = None) -> str:
    text = raw
    # 去除 OCR 雜訊行
    lines = text.split("\n")
    out = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        skip = False
        for pat in NOISE_PATTERNS:
            if re.search(pat, s):
                skip = True
                break
        if skip:
            continue
        # 英文 slogan 行
        if ENGLISH_SLOGAN.search(s) and len(re.sub(r"[A-Za-z\s]", "", s)) < 2:
            continue
        # 政黨名重複行
        if party_name and s == party_name:
            continue
        # 純數字行
        if re.fullmatch(r"[\d\.\-:]+", s):
            continue
        out.append(s)
    # 合併連續換行
    cleaned = "\n".join(out)
    # 修常見 OCR 錯：壓多個空白
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    today = date.today().isoformat()
    tag = f"[OCR 清理 by Claude {today}]"

    rows = conn.execute("""
        SELECT p.platform_id, p.content, p.note,
               (SELECT name FROM parties WHERE party_id=c.party_id) AS party_name
        FROM platforms p
        JOIN candidates c ON p.candidate_id=c.candidate_id
        WHERE p.note IS NULL OR p.note NOT LIKE '%人工潤稿%'
    """).fetchall()

    cleaned_cnt = 0
    for r in rows:
        new_content = clean_text(r["content"], r["party_name"])
        if not new_content or new_content == r["content"]:
            continue
        # 合併 note
        existing = r["note"] or ""
        new_note = (existing + (" · " if existing else "") + tag) if tag not in existing else existing
        conn.execute(
            "UPDATE platforms SET content=?, note=? WHERE platform_id=?",
            (new_content, new_note, r["platform_id"]),
        )
        cleaned_cnt += 1
    conn.commit()
    print(f"✓ 清理 {cleaned_cnt} 條政見")
    conn.close()


if __name__ == "__main__":
    main()
