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


def get_presidential_vote_trend() -> pd.DataFrame:
    """歷屆總統選舉各候選人得票，依日期排序"""
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
