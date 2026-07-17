"""Pydantic models for authorization domain."""

from pydantic import BaseModel, Field
from typing import Optional, List


class DecisionTrace(BaseModel):
    context_assembled: List[str]
    guideline_version: str
    reasoning: str
    agent_confidence: float


class Review(BaseModel):
    routed_to_human: bool
    final_decision_maker: str
    closed_by: Optional[str] = None
    closed_at: Optional[str] = None


class Authorization(BaseModel):
    authorization_id: str = Field(alias="_id")
    member_id: str
    requested_service: str
    status: str
    created_at: str
    # A freshly filed authorization is `pending` with no decision yet; the trace
    # and review are populated when it is processed (Phase 3, step 2).
    decision_trace: Optional[DecisionTrace] = None
    review: Optional[Review] = None

    class Config:
        populate_by_name = True


class MemberAuthorizationsResponse(BaseModel):
    member_id: str
    authorization_count: int
    authorizations: List[Authorization]


class PendingReviewResponse(BaseModel):
    count: int
    authorizations: List[Authorization]
