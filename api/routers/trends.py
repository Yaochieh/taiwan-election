from fastapi import APIRouter
from db import queries
from models import PresidentialTrend, PartyListTrend

router = APIRouter()


@router.get("/presidential", response_model=list[PresidentialTrend])
def presidential_trend():
    """歷屆總統選舉各正總統候選人得票（依日期排序）"""
    df = queries.get_presidential_vote_trend()
    return df.to_dict(orient="records")


@router.get("/party-list", response_model=list[PartyListTrend])
def party_list_trend():
    """歷屆立委不分區政黨票（依日期排序）"""
    df = queries.get_party_list_vote_trend()
    return df.to_dict(orient="records")
