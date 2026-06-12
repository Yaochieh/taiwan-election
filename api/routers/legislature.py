from fastapi import APIRouter
from db import queries

router = APIRouter()


@router.get("/{year}")
def legislature_composition(year: str):
    """指定年份立法院席次組成（含 113 立委分類、政黨總席次）"""
    return queries.get_legislative_seats(year)
