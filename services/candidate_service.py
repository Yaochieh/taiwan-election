import pandas as pd
from db import queries


def get_candidates_by_election(election_id: int) -> pd.DataFrame:
    return queries.get_candidates_by_election(election_id)


def get_candidate_detail(candidate_id: int) -> dict | None:
    return queries.get_candidate_by_id(candidate_id)


def get_results_by_election(election_id: int, district: str | None = None) -> pd.DataFrame:
    return queries.get_results_by_election(election_id, district)


def get_national_totals(election_id: int) -> pd.DataFrame:
    return queries.get_national_totals(election_id)
