"""API routes for prior-authorization decision traces (the Audit Log).

A prior authorization is a decision-trace document. These endpoints own its
lifecycle (file -> process -> review -> close) and the regulator-facing trail.
Route paths use the trace vocabulary; `trace_id` replaces the former `auth_id`.
"""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_connector
from .service import AuditService
from .models import (
    AuditTrace,
    MemberTracesResponse,
    MemberAuditTrailResponse,
    PendingReviewResponse,
    RoutingDecisionResponse,
    TracesListResponse,
)

router = APIRouter(prefix="/api/audit", tags=["audit"])


def get_audit_service(connector: MongoDBConnector = Depends(get_connector)) -> AuditService:
    return AuditService(connector)


# NOTE: "/traces" is a distinct path from "/traces/{trace_id}" (different segment
# count), so ordering is not load-bearing here the way it is for the literal
# "/traces/pending-review" declared below. Kept adjacent to the other collection
# reads for legibility.
@router.get("/traces", response_model=TracesListResponse)
async def list_all_traces(service: AuditService = Depends(get_audit_service)):
    """Every decision trace in the system, newest first (compliance-wide view)."""
    traces = service.list_all_traces()
    return {"count": len(traces), "traces": traces}


@router.post("/traces", response_model=AuditTrace)
async def create_trace(
    subject_ref: str,
    decision_type: str = "PRIOR_AUTHORIZATION",
    subject_type: str = "MEMBER",
    triggered_by: str = "system:insurance_agent",
    guideline_ref: str = None,
    input_facts: str = None,
    requested_service: str = None,
    service: AuditService = Depends(get_audit_service),
):
    """Insurance Agent, step 0: open an empty decision trace for a case.

    Returns the new trace with a generated `traceId` and empty `steps[]`. Nothing is
    decided here. Distinct from `/traces/file`, which is the provider filing a
    request; this is the insurance side opening the case shell.
    """
    try:
        return service.create_trace(
            subject_ref=subject_ref,
            decision_type=decision_type,
            subject_type=subject_type,
            triggered_by=triggered_by,
            guideline_ref=guideline_ref,
            input_facts=input_facts,
            requested_service=requested_service,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/traces/file", response_model=AuditTrace)
async def file_trace(
    member_id: str,
    requested_service: str,
    service: AuditService = Depends(get_audit_service),
):
    """Phase 3, step 1: file a formal prior-authorization request (pending trace)."""
    try:
        return service.file_trace(member_id=member_id, requested_service=requested_service)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/traces/process", response_model=AuditTrace)
async def process_trace(
    member_id: str,
    service: AuditService = Depends(get_audit_service),
):
    """Phase 3, step 2: process the member's pending trace — compute the decision,
    record the memory-typed steps + outcome, and apply bounded authority."""
    try:
        return service.process_trace(member_id=member_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/traces/pending-review", response_model=PendingReviewResponse)
async def get_pending_human_review(
    service: AuditService = Depends(get_audit_service),
):
    """All traces pending medical director review."""
    traces = service.get_pending_human_review()
    return {"count": len(traces), "traces": traces}


@router.get("/traces/{trace_id}", response_model=AuditTrace)
async def get_trace(
    trace_id: str, service: AuditService = Depends(get_audit_service)
):
    """Retrieve a specific decision trace."""
    doc = service.get_trace(trace_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")
    return doc


@router.get("/traces/{trace_id}/review")
async def open_human_review(
    trace_id: str,
    medical_director_id: str = None,
    service: AuditService = Depends(get_audit_service),
):
    """Phase 3a, step 2: assemble the brief for a medical director (full trace +
    broader member context)."""
    try:
        return service.open_human_review(trace_id, medical_director_id=medical_director_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/traces/{trace_id}/close", response_model=AuditTrace)
async def close_trace(
    trace_id: str,
    medical_director_id: str,
    decision: str,
    notes: str = "",
    service: AuditService = Depends(get_audit_service),
):
    """Phase 3a, step 3: a medical director sets the final decision on a routed
    trace (`decision`: `approved` or `denied`). Only routed traces can be
    human-closed — the agent never issues the final denial."""
    try:
        return service.close_trace(
            trace_id, medical_director_id=medical_director_id,
            decision=decision, notes=notes or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/traces/{trace_id}/steps", response_model=AuditTrace)
async def append_reasoning_step(
    trace_id: str,
    memory_type: str,
    name: str,
    detail: str,
    confidence: float,
    step_input: str = None,
    step_output: str = None,
    service: AuditService = Depends(get_audit_service),
):
    """Insurance Agent, steps 1-2: record one reasoning step, tagged by memory type.

    `memory_type` must be semantic, taxonomic, episodic or procedural — it is what
    makes the four-memory-type claim verifiable. Note that `episodic` and
    `procedural` mark the determination as clinical and remove the agent's authority
    to close it, so the administrative gates use `semantic` / `taxonomic`.

    `step_id` is assigned server-side. `step_input` / `step_output` accept JSON or
    prose.
    """
    try:
        return service.append_step(
            trace_id=trace_id,
            memory_type=memory_type,
            name=name,
            detail=detail,
            confidence=confidence,
            step_input=step_input,
            step_output=step_output,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/traces/{trace_id}/recommendation", response_model=AuditTrace)
async def record_recommendation(
    trace_id: str,
    decision: str,
    rationale: str,
    confidence: float,
    service: AuditService = Depends(get_audit_service),
):
    """Care-coordination agent, step 7: record the proposed outcome on the trace.

    Writes `outcome.decision`, `outcome.rationale` and `outcome.confidence`. Until
    this lands there is no recommendation for `/route` to act on.

    This tool only ever recommends: `review.*` and `audit.reviewRequired` are left
    alone, so who may close the case is still decided by the bounded-authority check
    rather than by whoever wrote the outcome.
    """
    try:
        return service.record_recommendation(
            trace_id=trace_id,
            decision=decision,
            rationale=rationale,
            confidence=confidence,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/traces/{trace_id}/route", response_model=RoutingDecisionResponse)
async def route_decision(
    trace_id: str, service: AuditService = Depends(get_audit_service)
):
    """Insurance Agent, step 8: the bounded-authority checkpoint.

    Computes, server-side, whether the agent may close this case or must escalate it:
    a clinical denial goes to a medical director at any confidence, and anything
    below the guideline threshold goes to one regardless of direction. Records its
    verdict on the trace so the checkpoint is auditable and the closure endpoints can
    enforce it.
    """
    try:
        return service.route_decision(trace_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/traces/{trace_id}/close-administrative", response_model=AuditTrace)
async def close_administrative_determination(
    trace_id: str,
    reason: str,
    closed_by: str = "system:insurance_agent",
    service: AuditService = Depends(get_audit_service),
):
    """Agent closure for a factual, non-clinical determination.

    `reason` must be `eligibility_lapsed` or `benefit_exclusion`. Refuses a denial
    reached through clinical reasoning, an already-routed trace, or a non-system
    identity — that refusal is the enforcement point for bounded authority, so a 400
    here is the correct answer and should be escalated rather than worked around.
    """
    try:
        return service.close_administrative(
            trace_id=trace_id, reason=reason, closed_by=closed_by
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/traces/{trace_id}/close-authorization", response_model=AuditTrace)
async def close_authorization(
    trace_id: str,
    closed_by: str = "system:insurance_agent",
    service: AuditService = Depends(get_audit_service),
):
    """Agent closure for a clinically-supported approval.

    Valid only for `approved` / `approved_restricted` at or above the guideline's
    confidence threshold. Never closes a denial.
    """
    try:
        return service.close_authorization(trace_id=trace_id, closed_by=closed_by)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/traces/{trace_id}/escalate", response_model=AuditTrace)
async def escalate_to_human(
    trace_id: str,
    reason: str,
    case_brief: str = None,
    final_decision_maker: str = "medical_director",
    service: AuditService = Depends(get_audit_service),
):
    """Route a case to a medical director, leaving it awaiting human closure.

    `review.closedBy` stays null — that null is how bounded authority is expressed in
    the data. The case pauses rather than ends; the member's pending action should
    stay `in_progress`. The human's closing action is
    `POST /api/audit/traces/{trace_id}/close`.
    """
    try:
        return service.escalate(
            trace_id=trace_id,
            reason=reason,
            case_brief=case_brief,
            final_decision_maker=final_decision_maker,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/member/{member_id}/traces", response_model=MemberTracesResponse)
async def get_member_traces(
    member_id: str, service: AuditService = Depends(get_audit_service)
):
    """All prior-authorization traces for a member."""
    traces = service.get_member_traces(member_id)
    return {"member_id": member_id, "trace_count": len(traces), "traces": traces}


@router.get("/member/{member_id}", response_model=MemberAuditTrailResponse)
async def get_member_audit_trail(
    member_id: str, service: AuditService = Depends(get_audit_service)
):
    """Regulator view: the member's decision traces, chronological."""
    traces = service.get_member_audit_trail(member_id)
    return {"member_id": member_id, "trace_count": len(traces), "traces": traces}
