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
)

router = APIRouter(prefix="/api/audit", tags=["audit"])


def get_audit_service(connector: MongoDBConnector = Depends(get_connector)) -> AuditService:
    return AuditService(connector)


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
