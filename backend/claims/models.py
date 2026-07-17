"""Pydantic models for claims domain."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class Claim(BaseModel):
    claim_id: str = Field(alias="_id")
    member_id: str
    service: str
    diagnosis: str
    outcome: str
    presentation_profile: Optional[Dict[str, Any]] = None
    adjudicated_at: Optional[str] = None

    class Config:
        populate_by_name = True


class ComparableClaim(BaseModel):
    """Projected shape returned by comparable-case retrieval (step 6).

    Only the fields the agent needs to judge similarity — service, outcome, and
    the presentation_profile — plus ids to cite the precedent.
    """
    claim_id: str = Field(alias="_id")
    member_id: Optional[str] = None
    service: str
    outcome: str
    presentation_profile: Optional[Dict[str, Any]] = None

    class Config:
        populate_by_name = True


class RefillGap(BaseModel):
    """A break in a medication's refill cadence, found in the pharmacy claims."""
    drug: str
    previous_fill: str
    next_fill: str
    gap_days: int
    approx_missed_fills: int


class RefillGapsResponse(BaseModel):
    member_id: str
    drug: Optional[str] = None
    expected_cadence_days: int
    count: int
    gaps: List[RefillGap]


class ComparableClaimsQuery(BaseModel):
    service: str
    diagnosis: str


class ComparableClaimsResponse(BaseModel):
    query: ComparableClaimsQuery
    count: int
    claims: List[ComparableClaim]


class MemberClaimsResponse(BaseModel):
    member_id: str
    claim_count: int
    claims: List[Claim]


class ClaimsList(BaseModel):
    count: int
    claims: List[Claim]
