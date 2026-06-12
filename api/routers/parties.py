from fastapi import APIRouter, Query
from api.utils import df_to_records
from db import queries
from models import Party, PartySeat, PartyByDate, PartyListVote

router = APIRouter()


@router.get("", response_model=list[Party])
def list_parties():
    """所有政黨"""
    df = queries.get_all_parties()
    return df_to_records(df)


@router.get("/seats", response_model=list[PartySeat])
def get_seats(election_id: int = Query(..., description="選舉 ID")):
    """某選舉的政黨席次"""
    df = queries.get_seats_by_election(election_id)
    return df_to_records(df)


@router.get("/results-by-date", response_model=list[PartyByDate])
def get_party_results_by_date(date: str = Query(..., description="投票日 YYYY-MM-DD")):
    """某投票日各政黨當選人數（跨所有選舉類型）"""
    df = queries.get_party_results_by_date(date)
    return df_to_records(df)


@router.get("/party-list-votes", response_model=list[PartyListVote])
def get_party_list_votes(date: str = Query(..., description="投票日 YYYY-MM-DD")):
    """立委不分區政黨票得票數"""
    df = queries.get_party_list_votes_by_date(date)
    return df_to_records(df)
