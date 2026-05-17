import pandas as pd
from db import queries


def get_all_parties() -> pd.DataFrame:
    return queries.get_all_parties()


def get_seats_by_election(election_id: int) -> pd.DataFrame:
    return queries.get_seats_by_election(election_id)


def get_election_cycles_with_results() -> pd.DataFrame:
    return queries.get_election_cycles_with_results()


def get_party_results_by_date(date: str) -> pd.DataFrame:
    return queries.get_party_results_by_date(date)
