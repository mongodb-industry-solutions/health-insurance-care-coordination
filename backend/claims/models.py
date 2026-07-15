"""Pydantic models for claims domain."""

from pydantic import BaseModel, Field
from typing import Optional, List


class Claim(BaseModel):
    claim_id: str = Field(alias="_id")
    member_id: str
    claim_date: str
    service: str
    diagnosis: str
    outcome: str
    amount: Optional[float] = None
    adjudication_date: Optional[str] = None

    class Config:
        populate_by_name = True


class ComparableClaimsQuery(BaseModel):
    service: str
    diagnosis: str


class ComparableClaimsResponse(BaseModel):
    query: ComparableClaimsQuery
    count: int
    claims: List[Claim]


class MemberClaimsResponse(BaseModel):
    member_id: str
    claim_count: int
    claims: List[Claim]


class ClaimsList(BaseModel):
    count: int
    claims: List[Claim]
