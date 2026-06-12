"""
建立 platforms 相關表，並從公報 PDF 匯入候選人政見。

新增表：
  - platform_categories: 政見分類
  - platforms:           候選人政見項目（單一條政見）
  - platform_sources:    政見來源（公報、官網、新聞等）

執行：
  python scripts/import_platforms.py --pdf data/bulletins/.../臺北市市長.pdf --election-id 53
  python scripts/import_platforms.py --auto   # 自動匹配公報與 DB 中的選舉
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from db.queries import get_connection
from scripts.parse_bulletin import parse_pdf
from scripts.parse_bulletin_v2 import parse_pdf as parse_pdf_v2, find_candidate_names_via_db

DB_PATH = ROOT / "data" / "db.sqlite"


def init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS platform_categories (
            category_id INTEGER PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            icon        TEXT
        );
        CREATE TABLE IF NOT EXISTS platforms (
            platform_id  INTEGER PRIMARY KEY,
            candidate_id INTEGER NOT NULL REFERENCES candidates(candidate_id),
            election_id  INTEGER NOT NULL REFERENCES elections(election_id),
            category_id  INTEGER REFERENCES platform_categories(category_id),
            seq          INTEGER NOT NULL,
            title        TEXT,
            content      TEXT NOT NULL,
            UNIQUE(candidate_id, election_id, seq)
        );
        CREATE TABLE IF NOT EXISTS platform_sources (
            source_id    INTEGER PRIMARY KEY,
            platform_id  INTEGER REFERENCES platforms(platform_id),
            candidate_id INTEGER REFERENCES candidates(candidate_id),
            election_id  INTEGER REFERENCES elections(election_id),
            source_type  TEXT NOT NULL,
            url          TEXT,
            local_path   TEXT,
            description  TEXT,
            fetched_at   TEXT
        );
    """)
    conn.commit()


def split_into_items(politics: str) -> list[str]:
    """把整段政見文字拆成單條政見。

    觀察 2022 公報：
      "1. 政見一內容\n2. 政見二內容\n..."  (阿拉伯數字)
      "一、政見一內容\n二、政見二內容\n..."  (中文數字)
    """
    if not politics or not politics.strip():
        return []

    text = politics.strip()
    # 嘗試阿拉伯數字 "1." / "1、" 分割
    items = re.split(r"(?:^|\n)\s*(\d{1,2})[\.\、]\s*", text)
    if len(items) >= 3:
        # 配對成 (num, content)
        result = []
        for i in range(1, len(items), 2):
            num = items[i]
            content = (items[i + 1] if i + 1 < len(items) else "").strip()
            if content:
                result.append(content)
        if len(result) >= 2:
            return _shift_orphan_numbers(result)

    # 中文數字 "一、" 分割
    cn_nums = "一二三四五六七八九十"
    items = re.split(rf"(?:^|\n)\s*([{cn_nums}]{{1,3}})[\、]\s*", text)
    if len(items) >= 3:
        result = []
        for i in range(1, len(items), 2):
            content = (items[i + 1] if i + 1 < len(items) else "").strip()
            if content:
                result.append(content)
        if len(result) >= 2:
            return _shift_orphan_numbers(result)

    # 都沒分到，當作整段政見
    return [text]


def _shift_orphan_numbers(items: list[str]) -> list[str]:
    """把每條結尾的孤立數字（被 PDF 切散的編號或範圍）轉移到下一條開頭。

    例如：
      原 [
        "...重建親民服務的市政府。\n0-6",
        "「歲小孩國家養」；...",
      ]
      → [
        "...重建親民服務的市政府。",
        "0-6 「歲小孩國家養」；...",
      ]

    處理規則：
      - 結尾若為一行純數字 / 範圍 / 短編號（≤8 字），且包含至少一個數字
      - 從本條移除，加上空白後黏到下一條開頭
      - 連續多行孤立數字都會被搬走
    """
    # 從尾巴往前移、再往下推
    for i in range(len(items) - 1):
        cur = items[i].rstrip()
        moved_parts: list[str] = []

        while True:
            m = re.search(r"\n([\d\-－—\s.、]{1,10})\s*$", cur)
            if not m:
                break
            tail = m.group(1).strip()
            # 必須包含數字，且不能是純標點
            if not re.search(r"\d", tail):
                break
            # 移除尾巴
            cur = cur[: m.start()].rstrip()
            moved_parts.insert(0, tail)

        if moved_parts:
            items[i] = cur
            prefix = " ".join(moved_parts).strip()
            items[i + 1] = (prefix + " " + items[i + 1]).strip()
    return items


def import_pdf(pdf_path: Path, election_id: int, source_url: str | None = None,
               dry_run: bool = False, district: str | None = None,
               parser: str = "v1"):
    """parser='v1' 用 pdfplumber 座標式（台北市公報專用）
       parser='v2' 用 PyMuPDF blocks（其他直轄市公報）"""
    if parser == "v2":
        names = find_candidate_names_via_db(election_id, district)
        v2_results = parse_pdf_v2(pdf_path, names)
        # 包裝成 v1 相容格式
        candidates = [
            {
                "name": r["name"],
                "politics": r["politics"],
                "education": "",
                "experience": "",
                "cand_num": None,
            }
            for r in v2_results
        ]
    else:
        candidates = parse_pdf(pdf_path)
    print(f"📋 解析 {pdf_path.name}：{len(candidates)} 位候選人")

    with get_connection() as conn:
        init_schema(conn)
        imported_platforms = 0
        imported_sources = 0
        skipped = 0

        for c in candidates:
            name = c["name"]
            if not name:
                continue

            # 找對應的 candidate_id
            row = conn.execute("""
                SELECT candidate_id FROM candidates
                WHERE election_id = ? AND name = ?
            """, (election_id, name)).fetchone()
            if not row:
                print(f"  ⚠️  找不到候選人「{name}」(election_id={election_id})，略過")
                skipped += 1
                continue
            candidate_id = row["candidate_id"]

            # 更新候選人 background（學歷 + 經歷）
            bg_parts = []
            if c["education"]:
                bg_parts.append(f"【學歷】\n{c['education']}")
            if c["experience"]:
                bg_parts.append(f"【經歷】\n{c['experience']}")
            background = "\n\n".join(bg_parts) if bg_parts else None
            if background:
                conn.execute(
                    "UPDATE candidates SET background = ? WHERE candidate_id = ?",
                    (background, candidate_id),
                )

            # 拆解政見
            items = split_into_items(c["politics"])
            if dry_run:
                print(f"  {name}: {len(items)} 條政見")
                for i, item in enumerate(items, 1):
                    print(f"    {i}. {item[:80]}{'...' if len(item) > 80 else ''}")
                continue

            for seq, content in enumerate(items, 1):
                conn.execute("""
                    INSERT INTO platforms (candidate_id, election_id, seq, content)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(candidate_id, election_id, seq) DO UPDATE
                        SET content = excluded.content
                """, (candidate_id, election_id, seq, content))
                imported_platforms += 1

            # 紀錄來源（不論政見是否空白都要記）
            submitted = len(items) > 0
            desc = "中選會選舉公報" if submitted else "中選會選舉公報（候選人未刊登政見）"
            conn.execute("""
                INSERT INTO platform_sources
                    (candidate_id, election_id, source_type, url, local_path, description, fetched_at)
                VALUES (?, ?, 'cec_bulletin', ?, ?, ?, datetime('now'))
            """, (
                candidate_id, election_id,
                source_url,
                str(pdf_path.resolve().relative_to(ROOT)),
                desc,
            ))
            imported_sources += 1

        if not dry_run:
            conn.commit()
            print(f"\n✓ 匯入 {imported_platforms} 條政見，{imported_sources} 筆來源紀錄，略過 {skipped} 位")


def find_election_id(conn, ad_year: int, office: str, region: str) -> int | None:
    """根據年份/職位/區域，匹配 elections 表中的 election_id"""
    cursor = conn.execute("""
        SELECT election_id, name, date FROM elections
        WHERE strftime('%Y', date) = ? AND type = ?
    """, (str(ad_year), office))
    rows = cursor.fetchall()
    return rows[0]["election_id"] if rows else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", help="公報 PDF 路徑")
    ap.add_argument("--election-id", type=int, help="DB 中對應的 election_id")
    ap.add_argument("--source-url", help="公報原始下載 URL")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--district", help="僅匹配此 district 的候選人（v2 parser 用）")
    ap.add_argument("--parser", choices=["v1", "v2"], default="v1")
    args = ap.parse_args()

    if not args.pdf or not args.election_id:
        ap.error("--pdf 和 --election-id 必須提供")

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"找不到 PDF：{pdf_path}", file=sys.stderr)
        sys.exit(1)

    import_pdf(pdf_path, args.election_id, args.source_url, args.dry_run,
               district=args.district, parser=args.parser)


if __name__ == "__main__":
    main()
