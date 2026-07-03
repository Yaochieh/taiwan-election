from fastapi import APIRouter, HTTPException
from db import queries

router = APIRouter()


@router.get("/trend/seats")
def legislative_seat_trend():
    """歷屆立委選舉各黨席次（區域 + 原住民），不含不分區"""
    return queries.get_legislative_trend()


@router.get("/{year}")
def legislature_composition(year: str):
    """指定年份立法院席次組成（含 113 立委分類、政黨總席次）"""
    result = queries.get_legislative_seats(year)
    if not result.get("parties") and not result.get("members"):
        raise HTTPException(status_code=404, detail=f"找不到 {year} 年立法院資料")
    return result
