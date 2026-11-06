"""Composed read routes.

Same paths, same shapes as before the data was split, so the frontend does not have to know
there are two databases:

    GET /api/members/{member_id}               the combined member document
    GET /api/audit/traces/{trace_id}           one trace, with its step text
    GET /api/audit/member/{member_id}/traces   a member's traces, with their step text
"""

from fastapi import APIRouter, Depends, HTTPException

from clinical.profiles.service import ProfileService
from clinical.reasoning.repository import ClinicalReasoningRepository
from db.mdb import (
    MongoDBConnector,
    get_clinical_connector,
    get_insurance_connector,
)
from insurance.members.service import MemberService
from insurance.reasoning.repository import AdminReasoningRepository
from traces.models import AuditTrace, MemberTracesResponse
from traces.service import TraceService

from .members import MemberView
from .models import Member
from .traces import TraceView

members_router = APIRouter(prefix="/api/members", tags=["members"])
audit_router = APIRouter(prefix="/api/audit", tags=["audit"])


def get_member_view(
    insurance: MongoDBConnector = Depends(get_insurance_connector),
    clinical: MongoDBConnector = Depends(get_clinical_connector),
) -> MemberView:
    return MemberView(MemberService(insurance), ProfileService(clinical))


def get_trace_view(
    insurance: MongoDBConnector = Depends(get_insurance_connector),
    clinical: MongoDBConnector = Depends(get_clinical_connector),
) -> TraceView:
    return TraceView(
        TraceService(insurance),
        AdminReasoningRepository(insurance),
        ClinicalReasoningRepository(clinical),
    )


@members_router.get("/{member_id}", response_model=Member)
async def get_member(member_id: str, view: MemberView = Depends(get_member_view)):
    """Retrieve the complete member document, composed from both databases."""
    doc = view.compose(member_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return doc


@audit_router.get("/traces/{trace_id}", response_model=AuditTrace)
async def get_trace(trace_id: str, view: TraceView = Depends(get_trace_view)):
    """Retrieve one decision trace, with each step's text filled in."""
    doc = view.get_trace(trace_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")
    return doc


@audit_router.get("/member/{member_id}/traces", response_model=MemberTracesResponse)
async def get_member_traces(member_id: str, view: TraceView = Depends(get_trace_view)):
    """All prior-authorization traces for a member."""
    traces = view.get_member_traces(member_id)
    return {"member_id": member_id, "trace_count": len(traces), "traces": traces}
