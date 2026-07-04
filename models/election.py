from datetime import datetime
from pydantic import BaseModel, Field


# ── 基礎模型 ──────────────────────────────────────────────────────────────────

class Election(BaseModel):
    election_id: int
    name: str
    type: str
    date: str
    status: str
    description: str | None = None
    theme_id: str | None = None


class ElectionDetail(Election):
    """選舉詳情，可包含額外統計欄位"""
    pass


class Party(BaseModel):
    party_id: int
    name: str
    abbreviation: str | None = None
    color_hex: str | None = None


class Candidate(BaseModel):
    candidate_id: int
    name: str
    party_name: str | None = None
    abbreviation: str | None = None
    color_hex: str | None = None
    district: str | None = None
    votes: float | None = None
    elected: int | None = None


class CandidateDetail(Candidate):
    background: str | None = None
    platform: str | None = None


class CandidateSearchResult(BaseModel):
    name: str
    district: str | None = None
    role: str | None = None  # 正/副總統
    date: str
    election_name: str
    election_type: str
    party_name: str | None = None
    votes: float | None = None
    elected: int | None = None


# ── 選舉結果 ──────────────────────────────────────────────────────────────────

class ElectionResult(BaseModel):
    district: str | None = None
    candidate_name: str
    background: str | None = None
    party_name: str | None = None
    color_hex: str | None = None
    votes: int
    elected: int


class NationalTotal(BaseModel):
    candidate_name: str
    party_name: str | None = None
    color_hex: str | None = None
    total_votes: float


# ── 政黨 ──────────────────────────────────────────────────────────────────────

class PartySeat(BaseModel):
    party_name: str
    abbreviation: str | None = None
    color_hex: str | None = None
    level: str
    count: int


class PartyByDate(BaseModel):
    party_name: str | None = None
    color_hex: str | None = None
    election_type: str
    description: str | None = None
    elected_count: int


class PartyListVote(BaseModel):
    party_name: str
    votes: int
    elected: int | None = None


# ── 摘要與統計 ────────────────────────────────────────────────────────────────

class ElectedCount(BaseModel):
    election_id: int
    elected_count: int


class ElectionCycle(BaseModel):
    date: str
    types: str | None = None
    total_elected: int


class District(BaseModel):
    district: str


# ── 政見 ──────────────────────────────────────────────────────────────────────

class Platform(BaseModel):
    seq: int
    content: str
    candidate_id: int | None = None
    candidate_name: str | None = None
    party_name: str | None = None
    color_hex: str | None = None
    source_url: str | None = None
    note: str | None = None
    content_raw: str | None = None


class PlatformSource(BaseModel):
    source_type: str
    url: str | None = None
    local_path: str | None = None
    description: str | None = None
    fetched_at: str | None = None


class PlatformImage(BaseModel):
    local_path: str
    url: str | None = None
    description: str | None = None
    ocr_text: str | None = None


class CandidatePlatformStatus(BaseModel):
    """候選人 + 政見狀態（用於政見頁面的清單）"""
    candidate_id: int
    candidate_name: str
    party_name: str | None = None
    color_hex: str | None = None
    district: str | None = None
    background: str | None = None  # 總統選舉用來區分 正總統 / 副總統
    votes: float | None = None
    elected: int | None = None
    photo_path: str | None = None
    platform_count: int = Field(description="文字政見數")
    image_count: int = Field(description="圖片政見張數")


# ── 趨勢 ──────────────────────────────────────────────────────────────────────

class PresidentialTrend(BaseModel):
    date: str
    candidate_name: str
    party_name: str | None = None
    votes: float


class PartyListTrend(BaseModel):
    date: str
    party_name: str
    votes: int
    elected: int | None = None


# ── 縣市長歷屆 ────────────────────────────────────────────────────────────────

class MayoralHistory(BaseModel):
    date: str
    district: str | None = None
    candidate_name: str
    party_name: str | None = None
    votes: int
    election_note: str | None = None


class TotalVotes(BaseModel):
    election_id: int
    total_votes: int


class TownshipResult(BaseModel):
    county: str
    township: str
    votes: int
    candidate_name: str
    background: str | None = None
    party_name: str | None = None
    color_hex: str | None = None
