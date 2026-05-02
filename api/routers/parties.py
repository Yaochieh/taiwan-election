from fastapi import APIRouter, HTTPException, Query
from services import party_service

router = APIRouter()


@router.get("")
def list_parties():
    df = party_service.get_all_parties()
    return df.to_dict(orient="records")


@router.get("/seats")
def get_seats(election_id: int = Query(..., description="選舉 ID")):
    df = party_service.get_seats_by_election(election_id)
    if df.empty:
        raise HTTPException(status_code=404, detail="查無席次資料")
    return df.to_dict(orient="records")
