import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "db.sqlite"

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS elections (
            election_id INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            type        TEXT NOT NULL,
            date        DATE NOT NULL,
            status      TEXT NOT NULL,
            description TEXT
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
            platform     TEXT
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
            votes        INTEGER NOT NULL,
            elected      BOOLEAN NOT NULL
        );
    """)
    conn.commit()
    conn.close()

def fetch_all(table: str) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
    conn.close()
    return df
