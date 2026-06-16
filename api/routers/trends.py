from fastapi import APIRouter
from api.utils import df_to_records
from db import queries
from models import PresidentialTrend, PartyListTrend

router = APIRouter()


@router.get("/presidential", response_model=list[PresidentialTrend])
def presidential_trend():
    """歷屆總統選舉各正總統候選人得票（依日期排序）"""
    df = queries.get_presidential_vote_trend()
    return df_to_records(df)


@router.get("/party-list", response_model=list[PartyListTrend])
def party_list_trend():
    """歷屆立委不分區政黨票（依日期排序）"""
    df = queries.get_party_list_vote_trend()
    return df_to_records(df)


@router.get("/presidential/county-winners")
def presidential_county_winners():
    """歷屆總統選舉各縣市勝出政黨（用於熱力圖）"""
    return queries.get_presidential_county_winners()


@router.get("/mayoral/county-winners")
def mayoral_county_winners():
    """歷屆縣市長選舉各縣市勝出政黨（用於熱力圖）"""
    return queries.get_mayoral_county_winners()
