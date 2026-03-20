import pandas as pd
from db.queries import fetch_all

def get_all_parties() -> pd.DataFrame:
    return fetch_all("parties")

def get_seats_by_party(election_id: int) -> pd.DataFrame:
    seats = fetch_all("seats")
    parties = fetch_all("parties")
    merged = seats.merge(parties, on="party_id")
    return merged[merged["election_id"] == election_id]
