import pandas as pd
from db import queries


def get_all_elections() -> pd.DataFrame:
    return queries.get_all_elections()


def get_elections_by_status(status: str) -> pd.DataFrame:
    return queries.get_elections_by_status(status)


def get_upcoming_elections() -> pd.DataFrame:
    return queries.get_elections_by_status("upcoming")


def get_historical_elections() -> pd.DataFrame:
    return queries.get_elections_by_status("historical")


def get_election(election_id: int) -> dict | None:
    return queries.get_election_by_id(election_id)
