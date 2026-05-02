from fastapi import APIRouter, HTTPException, Query
from services import candidate_service

router = APIRouter()


@router.get("")
def list_candidates(
    election_id: int = Query(..., description="選舉 ID"),
):
    df = candidate_service.get_candidates_by_election(election_id)
    if df.empty:
        raise HTTPException(status_code=404, detail="查無候選人資料")
    return df.to_dict(orient="records")


@router.get("/{candidate_id}")
def get_candidate(candidate_id: int):
    candidate = candidate_service.get_candidate_detail(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="候選人不存在")
    return candidate


@router.get("/results/{election_id}")
def get_results(
    election_id: int,
    district: str | None = Query(None, description="篩選縣市/選區"),
):
    df = candidate_service.get_results_by_election(election_id, district)
    if df.empty:
        raise HTTPException(status_code=404, detail="查無選舉結果")
    return df.to_dict(orient="records")


@router.get("/totals/{election_id}")
def get_national_totals(election_id: int):
    df = candidate_service.get_national_totals(election_id)
    if df.empty:
        raise HTTPException(status_code=404, detail="查無全國統計")
    return df.to_dict(orient="records")
