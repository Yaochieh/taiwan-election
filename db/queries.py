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
                SELECT er.district, c.name AS candidate_name,
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
            SELECT er.district, c.name AS candidate_name,
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
                   SUM(er.votes) AS votes
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
    """歷屆不分區政黨票，依日期排序"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT e.date, c.name AS party_name,
                   er.votes, er.elected
            FROM election_results er
            JOIN candidates c ON er.candidate_id = c.candidate_id
            JOIN elections e ON er.election_id = e.election_id
            WHERE e.description = '不分區政黨'
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


def get_mayoral_history() -> pd.DataFrame:
    """歷屆縣市長選舉當選結果"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT e.date, er.district, c.name AS candidate_name,
                   p.name AS party_name, er.votes
            FROM election_results er
            JOIN candidates c ON er.candidate_id = c.candidate_id
            JOIN elections e ON er.election_id = e.election_id
            LEFT JOIN parties p ON c.party_id = p.party_id
            WHERE e.type = 'mayoral' AND er.elected = 1
              AND e.description IS NULL
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
            SELECT DISTINCT e.election_id, e.name, e.date, e.type, e.description
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
        base_cols = """
            c.candidate_id, c.name AS candidate_name,
            p.name AS party_name, p.color_hex,
            er.district, er.votes, er.elected,
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
    """某候選人的圖片版政見。"""
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT local_path, url, description
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
                   SUM(r.votes) AS votes,
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
