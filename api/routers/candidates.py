from fastapi import APIRouter, HTTPException, Query
from api.utils import df_to_records
from db import queries
from models import (
    Candidate,
    CandidateDetail,
    CandidateSearchResult,
)

router = APIRouter()


@router.get("", response_model=list[Candidate])
def list_candidates(election_id: int = Query(..., description="選舉 ID")):
    """某選舉的候選人清單"""
    df = queries.get_candidates_by_election(election_id)
    return df_to_records(df)


@router.get("/search", response_model=list[CandidateSearchResult])
def search_candidates(q: str = Query(..., min_length=1, description="候選人姓名（支援部分比對）")):
    """跨選舉搜尋候選人"""
    df = queries.search_candidates(q)
    return df_to_records(df)


@router.get("/{candidate_id}", response_model=CandidateDetail)
def get_candidate(candidate_id: int):
    """單一候選人詳情"""
    candidate = queries.get_candidate_by_id(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候選人不存在")
    return candidate
