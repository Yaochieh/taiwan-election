from pydantic import BaseModel
from datetime import date
from typing import Optional, Literal

class Election(BaseModel):
    election_id: int
    name: str
    type: Literal["presidential", "legislative", "local"]
    date: date
    status: Literal["upcoming", "ongoing", "historical"]
    description: Optional[str] = None

class Party(BaseModel):
    party_id: int
    name: str
    abbreviation: str
    color_hex: str

class Candidate(BaseModel):
    candidate_id: int
    name: str
    party_id: int
    election_id: int
    district: Optional[str] = None
    background: Optional[str] = None
    platform: Optional[str] = None

class Seat(BaseModel):
    seat_id: int
    election_id: int
    party_id: int
    level: Literal["national", "city", "district"]
    count: int

class ElectionResult(BaseModel):
    result_id: int
    election_id: int
    candidate_id: int
    votes: int
    elected: bool
