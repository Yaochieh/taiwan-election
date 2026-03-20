import pandas as pd
from db.queries import fetch_all

def get_candidates_by_election(election_id: int) -> pd.DataFrame:
    df = fetch_all("candidates")
    return df[df["election_id"] == election_id]

def get_candidate_detail(candidate_id: int) -> pd.DataFrame:
    df = fetch_all("candidates")
    return df[df["candidate_id"] == candidate_id]
