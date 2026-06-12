from fastapi import APIRouter
from api.utils import df_to_records
from db import queries
from models import MayoralHistory

router = APIRouter()


@router.get("/history", response_model=list[MayoralHistory])
def mayoral_history():
    """歷屆縣市長當選結果"""
    df = queries.get_mayoral_history()
    return df_to_records(df)


