"""Pydantic models for the audit domain.

The Audit Log is the regulator-ready decision trace, created for a decision or
process tied to a member/claim (here: PRIOR_AUTHORIZATION). Its defining feature
is the `steps` array, where each reasoning step is explicitly tagged with the
memory type it represents — semantic / taxonomic / episodic / procedural — making
the demo's core claim (four memory types reasoning over one record) an inspectable
data structure.

This trace replaced the former `authorizations` collection: a prior-authorization
is a trace document. A few workflow fields (`requested_service`, `status`) are
carried alongside the canonical model fields so the file -> process -> close
lifecycle has somewhere to live.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class AuditMeta(BaseModel):
    triggered_by: Optional[str] = Field(default=None, alias="triggeredBy")
    triggered_at: Optional[str] = Field(default=None, alias="triggeredAt")
    review_required: bool = Field(default=False, alias="reviewRequired")
    review_required_reason: Optional[str] = Field(default=None, alias="reviewRequiredReason")
    regulatory_flags: List[str] = Field(default=[], alias="regulatoryFlags")
    retention_years: int = Field(default=7, alias="retentionYears")

    class Config:
        populate_by_name = True


class ContextSnapshot(BaseModel):
    guideline_ref: Optional[str] = Field(default=None, alias="guidelineRef")
    input_facts: List[str] = Field(default=[], alias="inputFacts")

    class Config:
        populate_by_name = True


class ReasoningStep(BaseModel):
    step_id: str = Field(alias="stepId")
    memory_type: str = Field(alias="memoryType")  # semantic|taxonomic|episodic|procedural
    name: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    confidence: Optional[float] = None
    detail: Optional[str] = None

    class Config:
        populate_by_name = True


class Outcome(BaseModel):
    decision: Optional[str] = None  # approved | denied | approved_restricted
    rationale: Optional[str] = None
    confidence: Optional[float] = None
    override_flag: bool = Field(default=False, alias="overrideFlag")
    override_by: Optional[str] = Field(default=None, alias="overrideBy")
    override_reason: Optional[str] = Field(default=None, alias="overrideReason")

    class Config:
        populate_by_name = True


class Review(BaseModel):
    routed_to_human: bool = Field(default=False, alias="routedToHuman")
    final_decision_maker: Optional[str] = Field(default=None, alias="finalDecisionMaker")
    closed_by: Optional[str] = Field(default=None, alias="closedBy")
    closed_at: Optional[str] = Field(default=None, alias="closedAt")
    # Medical director's closing rationale (Phase 3a) — part of the decision record.
    notes: Optional[str] = None

    class Config:
        populate_by_name = True


class LinkedTrace(BaseModel):
    trace_id: str = Field(alias="traceId")
    relationship: Optional[str] = None
    decision_type: Optional[str] = Field(default=None, alias="decisionType")
    occurred_at: Optional[str] = Field(default=None, alias="occurredAt")

    class Config:
        populate_by_name = True


class AuditTrace(BaseModel):
    trace_id: str = Field(alias="_id")
    decision_type: str = Field(default="PRIOR_AUTHORIZATION", alias="decisionType")
    subject_ref: str = Field(alias="subjectRef")
    subject_type: str = Field(default="MEMBER", alias="subjectType")

    # Workflow fields (lifecycle of the prior-auth request)
    requested_service: Optional[str] = None
    status: Optional[str] = None  # pending | approved | denied | pending_review

    audit: Optional[AuditMeta] = None
    context_snapshot: Optional[ContextSnapshot] = Field(default=None, alias="contextSnapshot")
    steps: List[ReasoningStep] = []
    outcome: Optional[Outcome] = None
    review: Optional[Review] = None
    linked_traces: List[LinkedTrace] = Field(default=[], alias="linkedTraces")

    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")

    class Config:
        populate_by_name = True


class MemberAuditTrailResponse(BaseModel):
    member_id: str
    trace_count: int
    traces: List[AuditTrace]


class MemberTracesResponse(BaseModel):
    member_id: str
    trace_count: int
    traces: List[AuditTrace]


class PendingReviewResponse(BaseModel):
    count: int
    traces: List[AuditTrace]
