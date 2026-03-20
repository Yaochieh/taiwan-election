import pandas as pd
from db.queries import fetch_all

def get_all_elections() -> pd.DataFrame:
    return fetch_all("elections")

def get_election_by_status(status: str) -> pd.DataFrame:
    df = get_all_elections()
    return df[df["status"] == status]

def get_upcoming_elections() -> pd.DataFrame:
    return get_election_by_status("upcoming")

def get_historical_elections() -> pd.DataFrame:
    return get_election_by_status("historical")
