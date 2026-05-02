import pandas as pd
from db import queries


def get_all_parties() -> pd.DataFrame:
    return queries.get_all_parties()


def get_seats_by_election(election_id: int) -> pd.DataFrame:
    return queries.get_seats_by_election(election_id)
