from fastapi import APIRouter, HTTPException, Query
from typing import Literal
from services import election_service

router = APIRouter()


@router.get("")
def list_elections(
    status: Literal["upcoming", "ongoing", "historical"] | None = Query(None)
):
    if status:
        df = election_service.get_elections_by_status(status)
    else:
        df = election_service.get_all_elections()
    return df.to_dict(orient="records")


@router.get("/{election_id}")
def get_election(election_id: int):
    election = election_service.get_election(election_id)
    if not election:
        raise HTTPException(status_code=404, detail="選舉不存在")
    return election
