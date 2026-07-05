"""選舉時程里程碑 seed（idempotent，可重跑）。

資料來源：中選會第622次委員會議通過之
「115年地方公職人員選舉投票日及工作進行程序表」
https://web.cec.gov.tw/central/article/61722

以投票日（vote_date）為鍵，同一投票日的多場選舉共用一組時程；
date_end 為 NULL 表示單日事件，有值表示期間。
"""
import sqlite3

DB = "data/db.sqlite"
SRC = "https://web.cec.gov.tw/central/article/61722"

MILESTONES_2026 = [
    # (date, date_end, label, note)
    ("2026-08-20", None, "發布選舉公告", None),
    ("2026-08-27", None, "公告候選人登記日期及必備事項", None),
    ("2026-08-31", "2026-09-04", "受理候選人登記", None),
    ("2026-10-16", None, "審定候選人名單", "審定後通知抽籤"),
    ("2026-10-23", None, "候選人抽籤決定號次", None),
    ("2026-11-08", None, "選舉人名冊編造完成", None),
    ("2026-11-12", None, "公告直轄市長候選人名單", None),
    ("2026-11-13", "2026-11-27", "直轄市長公辦政見發表會", None),
    ("2026-11-17", None, "公告直轄市議員、縣市長、縣市議員候選人名單", None),
    ("2026-11-18", "2026-11-27", "直轄市議員／縣市長／縣市議員公辦政見發表會", None),
    ("2026-11-24", None, "公告選舉人人數", None),
    ("2026-11-28", None, "投票、開票", "投票時間 08:00–16:00"),
]


def main():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS election_milestones (
            milestone_id INTEGER PRIMARY KEY,
            vote_date    DATE NOT NULL,
            date         DATE NOT NULL,
            date_end     DATE,
            label        TEXT NOT NULL,
            note         TEXT,
            source_url   TEXT NOT NULL,
            UNIQUE(vote_date, date, label)
        )
    """)
    n = 0
    for date, date_end, label, note in MILESTONES_2026:
        cur = conn.execute(
            """INSERT INTO election_milestones
               (vote_date, date, date_end, label, note, source_url)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(vote_date, date, label) DO UPDATE SET
                 date_end=excluded.date_end, note=excluded.note,
                 source_url=excluded.source_url""",
            ("2026-11-28", date, date_end, label, note, SRC),
        )
        n += cur.rowcount
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM election_milestones").fetchone()[0]
    print(f"✓ upsert {n} 筆，election_milestones 共 {total} 筆")


if __name__ == "__main__":
    main()
