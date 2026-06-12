"""Pydantic response models for FastAPI."""
from models.election import (
    Election,
    ElectionDetail,
    Party,
    Candidate,
    CandidateDetail,
    CandidateSearchResult,
    ElectionResult,
    NationalTotal,
    PartySeat,
    PartyByDate,
    PartyListVote,
    ElectedCount,
    ElectionCycle,
    Platform,
    PlatformSource,
    PlatformImage,
    CandidatePlatformStatus,
    PresidentialTrend,
    PartyListTrend,
    MayoralHistory,
    District,
)

__all__ = [
    "Election", "ElectionDetail", "Party", "Candidate", "CandidateDetail",
    "CandidateSearchResult", "ElectionResult", "NationalTotal", "PartySeat",
    "PartyByDate", "PartyListVote", "ElectedCount", "ElectionCycle",
    "Platform", "PlatformSource", "PlatformImage", "CandidatePlatformStatus",
    "PresidentialTrend", "PartyListTrend", "MayoralHistory", "District",
]
