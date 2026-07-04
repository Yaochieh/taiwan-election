from fastapi import APIRouter, HTTPException, Query
from api.utils import df_to_records
from db import queries
from models import (
    Election,
    Platform,
    PlatformSource,
    PlatformImage,
    CandidatePlatformStatus,
)

router = APIRouter()


@router.get("/elections", response_model=list[Election])
def list_elections_with_platforms():
    """列出有政見資料的選舉清單"""
    df = queries.get_elections_with_platforms()
    return df_to_records(df)


@router.get("/elections/{election_id}", response_model=list[Platform])
def list_platforms_by_election(election_id: int):
    """某選舉所有政見"""
    df = queries.get_platforms_by_election(election_id)
    if df.empty:
        return []
    return df_to_records(df)


@router.get("/elections/{election_id}/candidates-status",
            response_model=list[CandidatePlatformStatus])
def list_candidates_with_status(
    election_id: int,
    district: str | None = Query(None, description="篩選選區"),
):
    """某選舉所有候選人 + 政見狀態（文字 / 圖片 / 完全未繳）"""
    df = queries.get_candidates_with_platform_status(election_id, district)
    if df.empty:
        return []
    return df_to_records(df)


@router.get("/candidates/{candidate_id}",
            response_model=list[Platform])
def get_candidate_platforms(candidate_id: int, election_id: int = Query(...)):
    """某候選人在某選舉的政見條目"""
    df = queries.get_platforms_by_candidate(candidate_id, election_id)
    if df.empty:
        return []
    return df_to_records(df)


@router.get("/candidates/{candidate_id}/sources",
            response_model=list[PlatformSource])
def get_candidate_platform_sources(candidate_id: int, election_id: int = Query(...)):
    """某候選人的政見來源紀錄（公報 PDF URL 等）"""
    df = queries.get_platform_sources(candidate_id, election_id)
    return df_to_records(df)


@router.get("/candidates/{candidate_id}/images",
            response_model=list[PlatformImage])
def get_candidate_platform_images(candidate_id: int, election_id: int = Query(...)):
    """某候選人的圖片版政見（檔案路徑）"""
    df = queries.get_platform_images(candidate_id, election_id)
    return df_to_records(df)


@router.get("/targets/flagship")
def flagship_targets():
    """首頁兌現追蹤看板：旗艦承諾 + 最新進度與來源"""
    return queries.get_flagship_targets()
