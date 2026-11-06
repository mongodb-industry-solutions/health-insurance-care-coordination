"""Models for the shared authorization trace.

The trace (`audit_log`) is an *envelope*: header, `workflow` (the stage and whose turn it
is), the `request`, the `administrativeGates` result, step summaries, the `outcome` and the
`review`. It carries no step text, no input facts and no case brief. The text of each step
lives in the author's own reasoning collection and is joined on by `views/` when a trace is
read by a person (`steps[].detail`).

Field names keep the camelCase the stored documents use. `requested_service` is a legacy
alias, filled from `request.requestedService`, so the frontend's existing presenters keep
working.
"""

from pydantic import BaseModel, Field
from typing import Optional, List


class TraceStep(BaseModel):
    step_id: str = Field(alias="stepId")
    memory_type: str = Field(alias="memoryType")  # semantic|taxonomic|episodic|procedural
    # administrative (Insurance Agent) | clinical (Care-Coordination Agent)
    domain: Optional[str] = None
    recorded_by: Optional[str] = Field(default=None, alias="recordedBy")
    name: Optional[str] = None
    confidence: Optional[float] = None
    # Pointer to the full text in the author's reasoning collection.
    detail_ref: Optional[dict] = Field(default=None, alias="detailRef")
    # Filled in on read by `views/`, from `detailRef`. Never stored on the trace.
    detail: Optional[str] = None

    class Config:
        populate_by_name = True


class WorkflowEvent(BaseModel):
    stage: str
    actor: Optional[str] = None
    at: Optional[str] = None


class Workflow(BaseModel):
    # OPENED | ADMIN_CLEARED | CLINICAL_RECOMMENDED | ROUTED | ESCALATED | CLOSED
    stage: Optional[str] = None
    # insurance | care_coordination | medical_director | none
    next_actor: Optional[str] = Field(default=None, alias="nextActor")
    history: List[WorkflowEvent] = []

    class Config:
        populate_by_name = True


class CaseRequest(BaseModel):
    requested_service: Optional[str] = Field(default=None, alias="requestedService")
    action_id: Optional[str] = Field(default=None, alias="actionId")

    class Config:
        populate_by_name = True


class AdministrativeGates(BaseModel):
    """What the two administrative gates found. `coverage_restriction` is `none` or
    `partial`; `partial` means any approval has to be `approved_restricted`."""

    eligibility: Optional[str] = None  # passed | failed | null
    coverage: Optional[str] = None  # passed | failed | null
    coverage_restriction: Optional[str] = Field(default=None, alias="coverageRestriction")

    class Config:
        populate_by_name = True


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

    class Config:
        populate_by_name = True


class Outcome(BaseModel):
    decision: Optional[str] = None  # approved | approved_restricted | denied | pending
    rationale: Optional[str] = None
    confidence: Optional[float] = None
    confidence_threshold: Optional[float] = Field(default=None, alias="confidenceThreshold")
    guideline_ref: Optional[str] = Field(default=None, alias="guidelineRef")
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
    # The medical director's closing rationale.
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
    trace_id: str = Field(alias="traceId")
    decision_type: str = Field(default="PRIOR_AUTHORIZATION", alias="decisionType")
    subject_ref: str = Field(alias="subjectRef")
    subject_type: str = Field(default="MEMBER", alias="subjectType")

    status: Optional[str] = None  # pending | approved | approved_restricted | denied | pending_review
    workflow: Optional[Workflow] = None
    request: Optional[CaseRequest] = None
    administrative_gates: Optional[AdministrativeGates] = Field(
        default=None, alias="administrativeGates"
    )
    # Legacy alias of `request.requestedService`, so existing presenters keep working.
    requested_service: Optional[str] = None

    audit: Optional[AuditMeta] = None
    context_snapshot: Optional[ContextSnapshot] = Field(default=None, alias="contextSnapshot")
    steps: List[TraceStep] = []
    outcome: Optional[Outcome] = None
    review: Optional[Review] = None
    linked_traces: List[LinkedTrace] = Field(default=[], alias="linkedTraces")

    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")

    class Config:
        populate_by_name = True


class MemberTracesResponse(BaseModel):
    member_id: str
    trace_count: int
    traces: List[AuditTrace]
