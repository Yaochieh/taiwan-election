from fastapi import APIRouter, HTTPException, Query
from api.utils import df_to_records
from typing import Literal
from db import queries
from models import (
    Election,
    District,
    ElectedCount,
    ElectionCycle,
    ElectionResult,
    NationalTotal,
    TotalVotes,
    TownshipResult,
)

router = APIRouter()


@router.get("", response_model=list[Election])
def list_elections(
    status: Literal["upcoming", "ongoing", "historical", "completed"] | None = Query(None)
):
    """所有選舉清單，可用 status 篩選"""
    if status:
        df = queries.get_elections_by_status(status)
    else:
        df = queries.get_all_elections()
    return df_to_records(df)


@router.get("/cycles", response_model=list[ElectionCycle])
def list_election_cycles():
    """各投票日週期摘要（候選人總數等）"""
    df = queries.get_election_cycles_with_results()
    return df_to_records(df)


@router.get("/elected-counts", response_model=list[ElectedCount])
def list_elected_counts():
    """所有選舉的當選人數"""
    df = queries.get_elected_count_by_election()
    return df_to_records(df)


@router.get("/{election_id}", response_model=Election)
def get_election(election_id: int):
    """單筆選舉詳情"""
    election = queries.get_election_by_id(election_id)
    if not election:
        raise HTTPException(status_code=404, detail="選舉不存在")
    return election


@router.get("/{election_id}/districts", response_model=list[District])
def get_election_districts(election_id: int):
    """某選舉的所有選區"""
    df = queries.get_districts_for_election(election_id)
    return df_to_records(df)


@router.get("/{election_id}/results", response_model=list[ElectionResult])
def get_results(
    election_id: int,
    district: str | None = Query(None, description="篩選縣市/選區"),
):
    """某選舉所有結果（含每位候選人得票與當選旗標）"""
    df = queries.get_results_by_election(election_id, district)
    return df_to_records(df)


@router.get("/{election_id}/totals", response_model=list[NationalTotal])
def get_national_totals(election_id: int):
    """某選舉各候選人的全國得票加總"""
    df = queries.get_national_totals(election_id)
    return df_to_records(df)


@router.get("/{election_id}/total-votes", response_model=TotalVotes)
def get_total_votes(election_id: int):
    """某選舉的有效票總數"""
    total = queries.get_total_votes_by_election(election_id)
    return {"election_id": election_id, "total_votes": total}


@router.get("/{election_id}/townships", response_model=list[TownshipResult])
def get_township_results(
    election_id: int,
    county: str | None = Query(None, description="篩選縣市"),
):
    """某選舉的鄉鎮市區層級得票（總統選舉專用）"""
    rows = queries.get_township_results(election_id, county)
    return rows
