from fastapi import APIRouter, Query
from db import queries

router = APIRouter()


@router.get("")
def unified_search(
    q: str = Query(..., min_length=1, description="搜尋關鍵字"),
    limit: int = Query(30, ge=1, le=100),
):
    """跨站搜尋：候選人、政黨、選舉、政見、OCR 文字。"""
    return queries.unified_search(q, limit=limit)
