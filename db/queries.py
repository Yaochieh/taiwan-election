import sqlite3
import pandas as pd
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent.parent / "data" / "db.sqlite"


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS elections (
                election_id INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                type        TEXT NOT NULL,
                date        DATE NOT NULL,
                status      TEXT NOT NULL,
                description TEXT,
                theme_id    TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS parties (
                party_id     INTEGER PRIMARY KEY,
                name         TEXT NOT NULL,
                abbreviation TEXT NOT NULL,
                color_hex    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id INTEGER PRIMARY KEY,
                name         TEXT NOT NULL,
                party_id     INTEGER REFERENCES parties(party_id),
                election_id  INTEGER REFERENCES elections(election_id),
                district     TEXT,
                background   TEXT,
                platform     TEXT,
                UNIQUE(name, election_id)
            );
            CREATE TABLE IF NOT EXISTS seats (
                seat_id     INTEGER PRIMARY KEY,
                election_id INTEGER REFERENCES elections(election_id),
                party_id    INTEGER REFERENCES parties(party_id),
                level       TEXT NOT NULL,
                count       INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS election_results (
                result_id    INTEGER PRIMARY KEY,
                election_id  INTEGER REFERENCES elections(election_id),
                candidate_id INTEGER REFERENCES candidates(candidate_id),
                district     TEXT,
                votes        INTEGER NOT NULL,
                elected      BOOLEAN NOT NULL DEFAULT 0,
                UNIQUE(election_id, candidate_id, district)
            );
        """)
        conn.commit()


# ── Elections ──────────────────────────────────────────────────────────────────

def get_all_elections() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT * FROM elections ORDER BY date DESC", conn
        )


def get_elections_by_status(status: str) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT * FROM elections WHERE status = ? ORDER BY date DESC",
            conn, params=(status,)
        )


def get_election_by_id(election_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM elections WHERE election_id = ?", (election_id,)
        ).fetchone()
        return dict(row) if row else None


# ── Candidates ─────────────────────────────────────────────────────────────────

def get_candidates_by_election(election_id: int) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT c.candidate_id, c.name, c.district, c.background, c.platform,
                   p.name AS party_name, p.abbreviation, p.color_hex,
                   SUM(r.votes) AS votes,
                   MAX(r.elected) AS elected
            FROM candidates c
            LEFT JOIN parties p ON c.party_id = p.party_id
            LEFT JOIN election_results r ON r.candidate_id = c.candidate_id
                                        AND r.election_id = c.election_id
            WHERE c.election_id = ?
            GROUP BY c.candidate_id
            ORDER BY votes DESC NULLS LAST, c.candidate_id
            """,
            conn, params=(election_id,)
        )


def get_candidate_by_id(candidate_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT c.*, p.name AS party_name, p.abbreviation, p.color_hex,
                   SUM(r.votes) AS votes,
                   MAX(r.elected) AS elected
            FROM candidates c
            LEFT JOIN parties p ON c.party_id = p.party_id
            LEFT JOIN election_results r ON r.candidate_id = c.candidate_id
            WHERE c.candidate_id = ?
            GROUP BY c.candidate_id
            """,
            (candidate_id,)
        ).fetchone()
        return dict(row) if row else None


# ── Election results ───────────────────────────────────────────────────────────

def get_results_by_election(election_id: int, district: str | None = None) -> pd.DataFrame:
    with get_connection() as conn:
        if district:
            return pd.read_sql_query(
                """
                SELECT er.district, c.name AS candidate_name, c.background,
                       p.name AS party_name, p.color_hex,
                       er.votes, er.elected
                FROM election_results er
                JOIN candidates c ON er.candidate_id = c.candidate_id
                LEFT JOIN parties p ON c.party_id = p.party_id
                WHERE er.election_id = ? AND er.district = ?
                ORDER BY er.votes DESC
                """,
                conn, params=(election_id, district)
            )
        return pd.read_sql_query(
            """
            SELECT er.district, c.name AS candidate_name, c.background,
                   p.name AS party_name, p.color_hex,
                   er.votes, er.elected
            FROM election_results er
            JOIN candidates c ON er.candidate_id = c.candidate_id
            LEFT JOIN parties p ON c.party_id = p.party_id
            WHERE er.election_id = ?
            ORDER BY er.district, er.votes DESC
            """,
            conn, params=(election_id,)
        )


def get_national_totals(election_id: int) -> pd.DataFrame:
    """各候選人全國得票加總"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT c.name AS candidate_name,
                   p.name AS party_name, p.color_hex,
                   SUM(er.votes) AS total_votes
            FROM election_results er
            JOIN candidates c ON er.candidate_id = c.candidate_id
            LEFT JOIN parties p ON c.party_id = p.party_id
            WHERE er.election_id = ?
            GROUP BY er.candidate_id
            ORDER BY total_votes DESC
            """,
            conn, params=(election_id,)
        )


def get_total_votes_by_election(election_id: int) -> int:
    """選舉有效票總數（去重複計算）"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT SUM(votes) FROM election_results WHERE election_id = ?",
            (election_id,)
        ).fetchone()
        return int(row[0]) if row and row[0] else 0


# ── Parties & Seats ────────────────────────────────────────────────────────────

def get_all_parties() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT * FROM parties ORDER BY party_id", conn
        )


def get_election_cycles_with_results() -> pd.DataFrame:
    """各選舉週期（投票日）的摘要，只取有當選資料的"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT e.date, GROUP_CONCAT(DISTINCT e.type) AS types,
                   COUNT(er.result_id) AS total_elected
            FROM elections e
            JOIN election_results er ON e.election_id = er.election_id
            WHERE er.elected = 1
            GROUP BY e.date
            ORDER BY e.date DESC
            """,
            conn
        )


def get_party_results_by_date(date: str) -> pd.DataFrame:
    """指定投票日，各政黨當選人數（跨所有選舉類型）"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT p.name AS party_name, p.color_hex,
                   e.type AS election_type,
                   e.description,
                   COUNT(*) AS elected_count
            FROM election_results er
            JOIN candidates c ON er.candidate_id = c.candidate_id
            JOIN elections e ON er.election_id = e.election_id
            LEFT JOIN parties p ON c.party_id = p.party_id
            WHERE e.date = ? AND er.elected = 1
              AND (e.description IS NULL OR e.description != '不分區政黨')
            GROUP BY c.party_id, e.type, e.description
            ORDER BY e.type, elected_count DESC
            """,
            conn, params=(date,)
        )


def get_elected_count_by_election() -> pd.DataFrame:
    """各選舉的當選人數"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT e.election_id,
                   COUNT(er.result_id) AS elected_count
            FROM elections e
            LEFT JOIN election_results er ON er.election_id = e.election_id
                                         AND er.elected = 1
            GROUP BY e.election_id
            """,
            conn
        )


def get_presidential_vote_trend() -> pd.DataFrame:
    """歷屆總統選舉各候選人得票，依日期排序（只取正總統，避免正副重複計票）"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT e.date, c.name AS candidate_name,
                   p.name AS party_name,
                   -- 若有「全國」摘要列用它（已是總票）；否則 SUM 縣市
                   COALESCE(
                     SUM(CASE
                       WHEN er.district='全國' OR er.district LIKE '地區(0%' THEN er.votes
                     END),
                     SUM(CASE
                       WHEN er.district!='全國' AND er.district NOT LIKE '地區(0%' THEN er.votes
                     END)
                   ) AS votes
            FROM election_results er
            JOIN candidates c ON er.candidate_id = c.candidate_id
            JOIN elections e ON er.election_id = e.election_id
            LEFT JOIN parties p ON c.party_id = p.party_id
            WHERE e.type = 'presidential'
              AND COALESCE(c.background, '正總統') != '副總統'
            GROUP BY e.election_id, c.candidate_id
            ORDER BY e.date, votes DESC
            """,
            conn
        )


def get_party_list_vote_trend() -> pd.DataFrame:
    """歷屆不分區政黨票，依日期排序。

    僅取 election_results.votes > 0 的政黨層級 row，排除後加入的
    34 位「不分區當選人候選人」row（他們票數=0）。
    """
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT e.date, c.name AS party_name,
                   er.votes, er.elected
            FROM election_results er
            JOIN candidates c ON er.candidate_id = c.candidate_id
            JOIN elections e ON er.election_id = e.election_id
            WHERE e.description = '不分區政黨'
              AND er.votes > 0
            ORDER BY e.date, er.votes DESC
            """,
            conn
        )


def get_party_list_votes_by_date(date: str) -> pd.DataFrame:
    """立委不分區政黨票得票數（有資料才會有結果）"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT c.name AS party_name,
                   er.votes,
                   er.elected
            FROM election_results er
            JOIN candidates c ON er.candidate_id = c.candidate_id
            JOIN elections e ON er.election_id = e.election_id
            WHERE e.date = ? AND e.description = '不分區政黨'
              AND er.votes > 0
            ORDER BY er.votes DESC
            """,
            conn, params=(date,)
        )


def get_seats_by_election(election_id: int) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT p.name AS party_name, p.abbreviation, p.color_hex,
                   s.level, s.count
            FROM seats s
            JOIN parties p ON s.party_id = p.party_id
            WHERE s.election_id = ?
            ORDER BY s.count DESC
            """,
            conn, params=(election_id,)
        )


def get_person_targets(name: str) -> list[dict]:
    """取得某政治人物的所有政見追蹤目標（含進度資料點、多來源、父子結構）。

    回傳：父目標列表，每個父目標含 children[] 陣列。
    """
    with get_connection() as conn:
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='platform_targets'"
        )]
        if not tables:
            return []
        # 確認 v2 欄位存在（容錯）
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(platform_targets)")]
        has_parent = "parent_target_id" in cols
        has_kind = "data_source_kind" in cols
        has_rank = "rank" in cols
        has_pps = bool([r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='platform_progress_sources'"
        )])

        targets = conn.execute("""
            SELECT t.*,
                   e.name AS election_name, e.date AS election_date
            FROM platform_targets t
            LEFT JOIN elections e ON t.election_id = e.election_id
            WHERE t.person_name = ?
            ORDER BY t.rank, t.target_id
        """, (name,)).fetchall() if has_rank else conn.execute("""
            SELECT t.*,
                   e.name AS election_name, e.date AS election_date
            FROM platform_targets t
            LEFT JOIN elections e ON t.election_id = e.election_id
            WHERE t.person_name = ?
            ORDER BY t.category, t.target_id
        """, (name,)).fetchall()

        # 載入所有 progress + sources
        targets_by_id = {}
        for t in targets:
            row = dict(t)
            progress_rows = conn.execute("""
                SELECT progress_id, recorded_at, current_value, note, source_url
                FROM platform_target_progress
                WHERE target_id = ?
                ORDER BY recorded_at
            """, (t["target_id"],)).fetchall()
            progress = []
            for p in progress_rows:
                p_dict = dict(p)
                # 多來源
                if has_pps:
                    src_rows = conn.execute("""
                        SELECT url, source_type, publisher, authority_level
                        FROM platform_progress_sources
                        WHERE progress_id = ?
                        ORDER BY authority_level, source_id
                    """, (p["progress_id"],)).fetchall()
                    p_dict["sources"] = [dict(s) for s in src_rows]
                else:
                    p_dict["sources"] = []
                progress.append(p_dict)
            row["progress"] = progress

            # 進度百分比
            baseline = t["baseline_value"]
            target = t["target_value"]
            if baseline is not None and target is not None and target != baseline:
                latest = progress[-1]["current_value"] if progress else baseline
                pct = (latest - baseline) / (target - baseline) * 100
                row["progress_pct"] = round(max(0, min(100, pct)), 1)
                row["latest_value"] = latest
            else:
                row["progress_pct"] = None
                row["latest_value"] = None
            row["children"] = []
            targets_by_id[t["target_id"]] = row

        # 組成樹狀
        roots = []
        for tid, t in targets_by_id.items():
            parent_id = t.get("parent_target_id") if has_parent else None
            if parent_id and parent_id in targets_by_id:
                targets_by_id[parent_id]["children"].append(t)
            else:
                roots.append(t)
        return roots


def get_person_profile(name: str) -> dict:
    """聚合「同姓名」候選人跨選舉的所有資料。

    返回：候選人基本資料 + 每次參選紀錄（選舉、選區、政黨、得票、政見統計）。
    注意：同名候選人會合併。
    """
    with get_connection() as conn:
        # 候選人 id（同一姓名可能有多個 id，因為每場選舉新建一筆 candidate）
        # 將 election_results 按 candidate_id 聚合：
        # SUM(votes) 取得全國總票，MAX(elected) 表是否當選；
        # 避免總統選舉因為有「全國」與 22 個縣市的 row 而出現多筆。
        # 同一候選人若有多個 district（如 presidential per-county）只算一次。
        candidate_rows = conn.execute("""
            SELECT c.candidate_id, c.election_id, c.party_id, c.background,
                   c.district AS cand_district, c.photo_path,
                   p.name AS party_name, p.color_hex,
                   e.name AS election_name, e.type AS election_type,
                   e.date AS election_date, e.description AS election_desc,
                   -- 優先取全國摘要列；若無則取任一縣市
                   COALESCE(
                     c.district,
                     MAX(CASE WHEN er.district='全國' OR er.district LIKE '地區(0%' THEN er.district END),
                     MIN(er.district)
                   ) AS district,
                   -- 若有「全國」row 用它的票數，否則 SUM 縣市票數；
                   -- presidential 的「全國」row 已被 import 階段移除，所以這裡 SUM
                   -- 若有「全國摘要列」(全國 或 地區(0,0,0)) 用它的票數，
                   -- 否則 SUM 縣市票數
                   SUM(CASE
                       WHEN er.district='全國' OR er.district LIKE '地區(0%' THEN er.votes
                       ELSE 0
                   END) +
                   CASE WHEN COUNT(CASE
                       WHEN er.district='全國' OR er.district LIKE '地區(0%' THEN 1
                   END)=0 THEN COALESCE(SUM(er.votes), 0) ELSE 0 END AS votes,
                   MAX(er.elected) AS elected,
                   (SELECT COUNT(*) FROM platforms pl
                    WHERE pl.candidate_id = c.candidate_id) AS platform_count,
                   (SELECT COUNT(*) FROM platform_sources ps
                    WHERE ps.candidate_id = c.candidate_id
                          AND ps.source_type = 'image_platform') AS image_count
            FROM candidates c
            LEFT JOIN parties p ON c.party_id = p.party_id
            LEFT JOIN elections e ON c.election_id = e.election_id
            LEFT JOIN election_results er
                ON er.candidate_id = c.candidate_id
                   AND er.election_id = c.election_id
            WHERE c.name = ?
            GROUP BY c.candidate_id
            ORDER BY e.date DESC
        """, (name,)).fetchall()

        if not candidate_rows:
            return None  # type: ignore

        # 統整資料
        photo = None
        background = None
        for r in candidate_rows:
            if r["photo_path"] and not photo:
                photo = r["photo_path"]
            if r["background"] and not background:
                background = r["background"]

        races = []
        seen_keys = set()
        for r in candidate_rows:
            key = (r["election_id"], r["district"] or "")
            if key in seen_keys:
                continue
            seen_keys.add(key)
            race_dict = {
                "candidate_id": r["candidate_id"],
                "election_id": r["election_id"],
                "election_name": r["election_name"],
                "election_type": r["election_type"],
                "election_date": r["election_date"],
                "election_description": r["election_desc"],
                "district": r["district"],
                "party_name": r["party_name"],
                "color_hex": r["color_hex"],
                "votes": r["votes"],
                "elected": r["elected"],
                "platform_count": r["platform_count"],
                "image_count": r["image_count"],
                "background": r["background"],
            }
            # presidential：列出該候選人「在哪些縣市得票最高（勝選）」
            if r["election_type"] == "presidential":
                county_rows = conn.execute("""
                    SELECT er.district,
                           er.votes AS my_votes,
                           (SELECT MAX(er2.votes) FROM election_results er2
                            WHERE er2.election_id = er.election_id
                              AND er2.district = er.district) AS max_votes
                    FROM election_results er
                    WHERE er.election_id = ? AND er.candidate_id = ?
                      AND er.district != '全國' AND er.district NOT LIKE '地區(0%'
                """, (r["election_id"], r["candidate_id"])).fetchall()
                counties_won = [
                    c["district"]
                    for c in county_rows
                    if c["my_votes"] is not None and c["my_votes"] == c["max_votes"]
                ]
                race_dict["counties_won"] = counties_won
                race_dict["counties_total"] = len(county_rows)
            races.append(race_dict)

        # 政黨變遷：用「依日期由早到晚」的順序記錄首次出現
        # races 是 DESC 排序，需要反向迭代
        parties = []
        for r in reversed(races):
            p = r["party_name"] or "無黨籍"
            if not parties or parties[-1]["party"] != p:
                parties.append({
                    "party": p,
                    "color_hex": r["color_hex"],
                    "from_date": r["election_date"],
                })

        total_races = len(races)
        total_wins = sum(1 for r in races if r["elected"] == 1)

        return {
            "name": name,
            "photo_path": photo,
            "background": background,
            "total_races": total_races,
            "total_wins": total_wins,
            "win_rate": total_wins / total_races if total_races > 0 else 0,
            "races": races,
            "party_history": parties,
        }


def unified_search(query: str, limit: int = 50) -> dict:
    """跨站搜尋：候選人、政黨、選舉、政見內容。"""
    q_like = f"%{query}%"
    with get_connection() as conn:
        # 1. 候選人（按出現次數聚合）
        candidates = conn.execute("""
            SELECT c.name, COUNT(DISTINCT c.election_id) AS election_count,
                   MIN(c.election_id) AS sample_election_id,
                   MAX(CASE WHEN er.elected = 1 THEN 1 ELSE 0 END) AS ever_elected,
                   GROUP_CONCAT(DISTINCT p.name) AS parties
            FROM candidates c
            LEFT JOIN election_results er
                ON er.candidate_id = c.candidate_id
            LEFT JOIN parties p ON c.party_id = p.party_id
            WHERE c.name LIKE ?
            GROUP BY c.name
            ORDER BY election_count DESC, ever_elected DESC
            LIMIT ?
        """, (q_like, limit)).fetchall()

        # 2. 政黨
        parties = conn.execute("""
            SELECT party_id, name, abbreviation, color_hex
            FROM parties
            WHERE name LIKE ? OR abbreviation LIKE ?
            LIMIT ?
        """, (q_like, q_like, limit)).fetchall()

        # 3. 選舉
        elections = conn.execute("""
            SELECT election_id, name, type, date, status, description
            FROM elections
            WHERE name LIKE ? OR description LIKE ?
            ORDER BY date DESC
            LIMIT ?
        """, (q_like, q_like, limit)).fetchall()

        # 4. 政見內容（取前 N 個 snippet）
        platforms = conn.execute("""
            SELECT pl.platform_id, pl.candidate_id, pl.election_id, pl.content,
                   c.name AS candidate_name,
                   p.name AS party_name, p.color_hex,
                   e.name AS election_name, e.date AS election_date
            FROM platforms pl
            JOIN candidates c ON pl.candidate_id = c.candidate_id
            JOIN elections e ON pl.election_id = e.election_id
            LEFT JOIN parties p ON c.party_id = p.party_id
            WHERE pl.content LIKE ?
            ORDER BY e.date DESC
            LIMIT ?
        """, (q_like, limit)).fetchall()

        # 5. OCR 文字
        ocr_cols = [r["name"] for r in conn.execute("PRAGMA table_info(platform_sources)")]
        ocr_hits = []
        if "ocr_text" in ocr_cols:
            ocr_rows = conn.execute("""
                SELECT ps.candidate_id, ps.election_id, ps.ocr_text, ps.local_path,
                       c.name AS candidate_name,
                       p.name AS party_name, p.color_hex,
                       e.name AS election_name, e.date AS election_date
                FROM platform_sources ps
                JOIN candidates c ON ps.candidate_id = c.candidate_id
                JOIN elections e ON ps.election_id = e.election_id
                LEFT JOIN parties p ON c.party_id = p.party_id
                WHERE ps.source_type = 'image_platform' AND ps.ocr_text LIKE ?
                ORDER BY e.date DESC
                LIMIT ?
            """, (q_like, limit)).fetchall()
            # 抽取包含關鍵字的片段
            for r in ocr_rows:
                text = r["ocr_text"]
                idx = text.find(query)
                if idx == -1:
                    continue
                start = max(0, idx - 40)
                end = min(len(text), idx + len(query) + 80)
                snippet = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
                ocr_hits.append({
                    **dict(r),
                    "snippet": snippet,
                })

        # 為 platforms 也產生 snippet
        platforms_with_snippet = []
        for r in platforms:
            content = r["content"]
            idx = content.find(query)
            if idx == -1:
                idx = 0
            start = max(0, idx - 40)
            end = min(len(content), idx + len(query) + 80)
            snippet = ("..." if start > 0 else "") + content[start:end] + ("..." if end < len(content) else "")
            platforms_with_snippet.append({
                **dict(r),
                "snippet": snippet,
            })

        return {
            "query": query,
            "candidates": [dict(r) for r in candidates],
            "parties": [dict(r) for r in parties],
            "elections": [dict(r) for r in elections],
            "platforms": platforms_with_snippet,
            "ocr": ocr_hits,
            "total": (
                len(candidates) + len(parties) + len(elections)
                + len(platforms_with_snippet) + len(ocr_hits)
            ),
        }


def get_legislative_seats(year: str) -> dict:
    """回傳指定年份立法院席次組成。
    113 席 = 73 區域 + 3 山地原住民 + 3 平地原住民 + 34 不分區（Hare quota）
    """
    import math
    with get_connection() as conn:
        # 找到該年的選舉 ID
        elections = conn.execute("""
            SELECT election_id, description FROM elections
            WHERE type = 'legislative' AND date LIKE ?
        """, (f"{year}%",)).fetchall()
        if not elections:
            return {"parties": [], "members": []}

        ids = {e["description"]: e["election_id"] for e in elections}

        results = {
            "regional": [],     # 73
            "highland": [],     # 3
            "lowland": [],      # 3
            "party_list": [],   # 34
        }

        # ── 1. 區域立委：每選區 elected=1 一名 ──
        if "區域" in ids:
            rows = conn.execute("""
                SELECT er.district, c.name, p.name as party, p.color_hex, er.votes
                FROM election_results er
                JOIN candidates c ON er.candidate_id = c.candidate_id
                LEFT JOIN parties p ON c.party_id = p.party_id
                WHERE er.election_id = ? AND er.elected = 1
            """, (ids["區域"],)).fetchall()
            for r in rows:
                results["regional"].append({
                    "kind": "regional",
                    "district": r["district"],
                    "candidate": r["name"],
                    "party": r["party"] or "無黨籍",
                    "color_hex": r["color_hex"],
                    "votes": r["votes"],
                })

        # ── 2. 山地原住民：取前 3 高票 ──
        for kind, key, eid_key in [("highland", "山地原住民", "山地原住民"),
                                    ("lowland", "平地原住民", "平地原住民")]:
            eid = ids.get(eid_key)
            if not eid:
                continue
            rows = conn.execute("""
                SELECT c.name, p.name as party, p.color_hex, er.votes
                FROM election_results er
                JOIN candidates c ON er.candidate_id = c.candidate_id
                LEFT JOIN parties p ON c.party_id = p.party_id
                WHERE er.election_id = ?
                ORDER BY er.votes DESC LIMIT 3
            """, (eid,)).fetchall()
            for r in rows:
                results[kind].append({
                    "kind": kind,
                    "district": "全國",
                    "candidate": r["name"],
                    "party": r["party"] or "無黨籍",
                    "color_hex": r["color_hex"],
                    "votes": r["votes"],
                })

        # ── 3. 不分區：Hare quota 計算 34 席 ──
        if "不分區政黨" in ids:
            rows = conn.execute("""
                SELECT c.name as party, p.color_hex, er.votes
                FROM election_results er
                JOIN candidates c ON er.candidate_id = c.candidate_id
                LEFT JOIN parties p ON p.name = c.name
                WHERE er.election_id = ?
                ORDER BY er.votes DESC
            """, (ids["不分區政黨"],)).fetchall()

            total_seats = 34
            threshold = 0.05
            total_votes = sum(r["votes"] for r in rows)
            # 過門檻政黨
            qualifying = [r for r in rows if r["votes"] >= total_votes * threshold]
            qual_votes = sum(r["votes"] for r in qualifying)

            if qual_votes > 0:
                quota = qual_votes / total_seats
                seats_dict = {}
                remainders = {}
                for r in qualifying:
                    base = math.floor(r["votes"] / quota)
                    seats_dict[r["party"]] = base
                    remainders[r["party"]] = (r["votes"] / quota) - base

                # 用最大餘數法分配剩餘席次
                remaining = total_seats - sum(seats_dict.values())
                sorted_parties = sorted(remainders.items(), key=lambda x: -x[1])
                for i in range(remaining):
                    party = sorted_parties[i % len(sorted_parties)][0]
                    seats_dict[party] = seats_dict.get(party, 0) + 1

                for party, seats in seats_dict.items():
                    color = next((r["color_hex"] for r in rows if r["party"] == party), None)
                    # 嘗試從 candidates 表取真實 (黨內 順位) 名單
                    real_names = conn.execute("""
                        SELECT c.name, c.background
                        FROM candidates c
                        LEFT JOIN parties p ON c.party_id = p.party_id
                        WHERE c.election_id = ?
                          AND p.name = ?
                          AND c.background LIKE '不分區立委%'
                        ORDER BY c.background  -- 含「第 N 順位」字串依字典序大致符合 rank
                    """, (ids["不分區政黨"], party)).fetchall()
                    # 解析 background 取 rank
                    parsed = []
                    for nr in real_names:
                        import re as _re
                        m = _re.search(r"第\s*(\d+)\s*順位", nr["background"] or "")
                        if m:
                            parsed.append((int(m.group(1)), nr["name"]))
                    parsed.sort()
                    for i in range(seats):
                        if i < len(parsed):
                            name = parsed[i][1]
                        else:
                            name = f"({party} 第 {i+1} 順位)"
                        results["party_list"].append({
                            "kind": "party_list",
                            "district": "不分區",
                            "candidate": name,
                            "party": party,
                            "color_hex": color,
                            "votes": 0,
                        })

        # ── 整合：合併所有 113 席 ──
        all_members = (results["regional"] + results["highland"] +
                       results["lowland"] + results["party_list"])

        # 計算各黨總席次
        party_counts = {}
        for m in all_members:
            p = m["party"]
            if p not in party_counts:
                party_counts[p] = {
                    "name": p, "color_hex": m["color_hex"],
                    "regional": 0, "aboriginal": 0, "party_list": 0, "total": 0,
                }
            if m["kind"] == "regional":
                party_counts[p]["regional"] += 1
            elif m["kind"] in ("highland", "lowland"):
                party_counts[p]["aboriginal"] += 1
            elif m["kind"] == "party_list":
                party_counts[p]["party_list"] += 1
            party_counts[p]["total"] += 1

        parties = sorted(party_counts.values(), key=lambda p: -p["total"])

        return {
            "year": year,
            "total_seats": len(all_members),
            "parties": parties,
            "members": all_members,
        }


def _compute_party_list_seats(conn, election_id: int, total_seats: int = 34) -> dict[str, int]:
    """Hare quota + 最大餘數法計算不分區席次。"""
    rows = conn.execute("""
        SELECT c.name AS party_name, er.votes
        FROM election_results er
        JOIN candidates c ON er.candidate_id = c.candidate_id
        WHERE er.election_id = ? AND er.elected = 1 AND er.votes > 0
    """, (election_id,)).fetchall()
    if not rows:
        return {}
    total = sum(r["votes"] for r in rows)
    if total == 0:
        return {}
    quota = total / total_seats
    base = {}
    remainder = {}
    for r in rows:
        b = int(r["votes"] // quota)
        base[r["party_name"]] = b
        remainder[r["party_name"]] = r["votes"] - b * quota
    allocated = sum(base.values())
    leftover = total_seats - allocated
    for party, _ in sorted(remainder.items(), key=lambda x: -x[1])[:leftover]:
        base[party] = base.get(party, 0) + 1
    return {p: s for p, s in base.items() if s > 0}


def get_legislative_trend() -> list[dict]:
    """歷屆立委選舉各黨席次（區域+原住民+不分區）。

    立委選舉年份：2008、2012、2016、2020、2024（每屆 113 席）
    - 區域: 73 + 山地原住民 3 + 平地原住民 3 = 79 席
      → 直接 COUNT(elected=1)
    - 不分區: 34 席（Hare quota 配額計算）
      → 由「不分區政黨」選舉的得票率計算
    """
    with get_connection() as conn:
        # 區域 + 原住民
        regional_rows = conn.execute("""
            SELECT strftime('%Y', e.date) AS year,
                   COALESCE(p.name, '無黨籍') AS party,
                   p.color_hex,
                   COUNT(*) AS seats
            FROM election_results er
            JOIN candidates c ON er.candidate_id = c.candidate_id
            JOIN elections e ON er.election_id = e.election_id
            LEFT JOIN parties p ON c.party_id = p.party_id
            WHERE e.type='legislative' AND er.elected = 1
              AND strftime('%Y', e.date) IN ('2008','2012','2016','2020','2024')
              AND (e.description IS NULL OR e.description NOT LIKE '%不分區%')
            GROUP BY year, party
        """).fetchall()
        seat_map: dict[tuple[str, str], dict] = {}
        for r in regional_rows:
            key = (r["year"], r["party"])
            seat_map[key] = {
                "year": r["year"],
                "party": r["party"],
                "color_hex": r["color_hex"],
                "seats": r["seats"],
            }

        # 不分區（Hare quota）
        pl_elections = conn.execute("""
            SELECT election_id, strftime('%Y', date) AS year
            FROM elections
            WHERE type='legislative' AND description LIKE '%不分區%'
              AND strftime('%Y', date) IN ('2008','2012','2016','2020','2024')
        """).fetchall()
        for e in pl_elections:
            seats = _compute_party_list_seats(conn, e["election_id"])
            # 取得 color_hex
            for party_name, n in seats.items():
                color = conn.execute(
                    "SELECT color_hex FROM parties WHERE name = ?", (party_name,)
                ).fetchone()
                key = (e["year"], party_name)
                if key in seat_map:
                    seat_map[key]["seats"] += n
                else:
                    seat_map[key] = {
                        "year": e["year"],
                        "party": party_name,
                        "color_hex": color["color_hex"] if color else None,
                        "seats": n,
                    }

        out = sorted(seat_map.values(), key=lambda x: (x["year"], -x["seats"]))
        return out


def get_mayoral_history() -> pd.DataFrame:
    """歷屆縣市長選舉當選結果（含補選、重新選舉）"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT e.date, er.district, c.name AS candidate_name,
                   p.name AS party_name, er.votes,
                   e.description AS election_note
            FROM election_results er
            JOIN candidates c ON er.candidate_id = c.candidate_id
            JOIN elections e ON er.election_id = e.election_id
            LEFT JOIN parties p ON c.party_id = p.party_id
            WHERE e.type = 'mayoral' AND er.elected = 1
              AND (
                e.description IS NULL
                OR e.description LIKE '%補選%'
                OR e.description LIKE '%重新%'
                OR e.description LIKE '%重行%'
                OR e.description LIKE '%罷免%'
              )
            ORDER BY e.date, er.votes DESC
            """,
            conn
        )


def get_platforms_by_election(election_id: int) -> pd.DataFrame:
    """某選舉中所有有政見的候選人，及他們的政見條目。"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT c.candidate_id, c.name AS candidate_name,
                   p.name AS party_name, p.color_hex,
                   pl.seq, pl.content
            FROM platforms pl
            JOIN candidates c ON pl.candidate_id = c.candidate_id
            LEFT JOIN parties p ON c.party_id = p.party_id
            WHERE pl.election_id = ?
            ORDER BY c.candidate_id, pl.seq
            """,
            conn, params=(election_id,)
        )


def get_platform_sources(candidate_id: int, election_id: int) -> pd.DataFrame:
    """某候選人在某場選舉的政見來源。"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT source_type, url, local_path, description, fetched_at
            FROM platform_sources
            WHERE candidate_id = ? AND election_id = ?
            ORDER BY fetched_at DESC
            """,
            conn, params=(candidate_id, election_id)
        )


def get_elections_with_platforms() -> pd.DataFrame:
    """有政見資料或有政見來源紀錄的選舉清單。"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT DISTINCT e.election_id, e.name, e.date, e.type, e.status, e.description
            FROM elections e
            WHERE e.election_id IN (
                SELECT election_id FROM platforms
                UNION
                SELECT election_id FROM platform_sources
            )
            ORDER BY e.date DESC
            """,
            conn
        )


def get_candidates_with_platform_status(election_id: int, district: str | None = None) -> pd.DataFrame:
    """某選舉所有候選人，含政見條數、圖片政見張數、來源資訊。
    用於政見頁面顯示——包含未繳交政見的候選人。
    """
    with get_connection() as conn:
        # 容錯：photo_path 欄位可能還不存在
        cols_check = [r["name"] for r in conn.execute("PRAGMA table_info(candidates)")]
        photo_col = "c.photo_path" if "photo_path" in cols_check else "NULL AS photo_path"
        base_cols = f"""
            c.candidate_id, c.name AS candidate_name,
            p.name AS party_name, p.color_hex,
            er.district, er.votes, er.elected,
            {photo_col},
            (SELECT COUNT(*) FROM platforms pl
             WHERE pl.candidate_id = c.candidate_id AND pl.election_id = ?) AS platform_count,
            (SELECT COUNT(*) FROM platform_sources ps
             WHERE ps.candidate_id = c.candidate_id AND ps.election_id = ?
                   AND ps.source_type = 'image_platform') AS image_count
        """
        if district:
            q = f"""
                SELECT {base_cols}
                FROM candidates c
                JOIN election_results er
                    ON er.candidate_id = c.candidate_id AND er.election_id = c.election_id
                LEFT JOIN parties p ON c.party_id = p.party_id
                WHERE c.election_id = ? AND er.district = ?
                ORDER BY er.elected DESC, er.votes DESC
            """
            params = (election_id, election_id, election_id, district)
        else:
            q = f"""
                SELECT {base_cols}
                FROM candidates c
                JOIN election_results er
                    ON er.candidate_id = c.candidate_id AND er.election_id = c.election_id
                LEFT JOIN parties p ON c.party_id = p.party_id
                WHERE c.election_id = ?
                GROUP BY c.candidate_id
                ORDER BY er.elected DESC, er.votes DESC
            """
            params = (election_id, election_id, election_id)
        return pd.read_sql_query(q, conn, params=params)


def get_platform_images(candidate_id: int, election_id: int) -> pd.DataFrame:
    """某候選人的圖片版政見（含 OCR 文字）。"""
    with get_connection() as conn:
        # 容錯：ocr_text 欄位可能還不存在
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(platform_sources)")]
        ocr_col = ", ocr_text" if "ocr_text" in cols else ", NULL as ocr_text"
        return pd.read_sql_query(
            f"""
            SELECT local_path, url, description{ocr_col}
            FROM platform_sources
            WHERE candidate_id = ? AND election_id = ? AND source_type = 'image_platform'
            ORDER BY source_id
            """,
            conn, params=(candidate_id, election_id)
        )


def get_districts_for_election(election_id: int) -> pd.DataFrame:
    """某選舉的所有選區清單。"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT DISTINCT district FROM election_results
            WHERE election_id = ?
            ORDER BY district
            """,
            conn, params=(election_id,)
        )


def search_candidates(query: str) -> pd.DataFrame:
    """跨選舉搜尋候選人"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT c.name, c.district, c.background AS role,
                   e.date, e.name AS election_name, e.type AS election_type,
                   p.name AS party_name,
                   -- 若有「全國」摘要列用它；否則 SUM 縣市
                   COALESCE(
                     SUM(CASE
                       WHEN r.district='全國' OR r.district LIKE '地區(0%' THEN r.votes
                     END),
                     SUM(CASE
                       WHEN r.district!='全國' AND r.district NOT LIKE '地區(0%' THEN r.votes
                     END)
                   ) AS votes,
                   MAX(r.elected) AS elected
            FROM candidates c
            JOIN elections e ON c.election_id = e.election_id
            LEFT JOIN parties p ON c.party_id = p.party_id
            LEFT JOIN election_results r ON r.candidate_id = c.candidate_id AND r.election_id = c.election_id
            WHERE c.name LIKE ?
            GROUP BY c.candidate_id
            ORDER BY e.date DESC
            """,
            conn, params=(f"%{query}%",)
        )


def get_township_results(election_id: int, county: str | None = None) -> list[dict]:
    """鄉鎮市區層級得票（總統選舉）"""
    sql = """
        SELECT tr.county, tr.township, tr.votes,
               c.name AS candidate_name, c.background,
               p.name AS party_name, p.color_hex
        FROM township_results tr
        JOIN candidates c ON tr.candidate_id = c.candidate_id
        LEFT JOIN parties p ON c.party_id = p.party_id
        WHERE tr.election_id = ?
    """
    params: list = [election_id]
    if county:
        sql += " AND tr.county = ?"
        params.append(county)
    sql += " ORDER BY tr.county, tr.township, tr.votes DESC"
    with get_connection() as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    return df.to_dict(orient="records")
