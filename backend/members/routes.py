"""API routes for member operations."""

from fastapi import APIRouter, Depends, HTTPException
from typing import Union

from db.mdb import MongoDBConnector, get_connector
from .service import MemberService
from .models import (
    Member,
    MemberClinicalContext,
    MemberList,
    MemberSummaryResponse,
    PendingActionUpdateResponse,
    PendingAuthorizationsResponse,
)

router = APIRouter(prefix="/api/members", tags=["members"])


def get_member_service(connector: MongoDBConnector = Depends(get_connector)) -> MemberService:
    return MemberService(connector)


# NOTE: this route MUST stay above `/{member_id}`. FastAPI matches in declaration
# order, so a literal segment declared after a path parameter is unreachable —
# "pending-authorizations" would be swallowed as a member id and 404.
@router.get("/pending-authorizations", response_model=PendingAuthorizationsResponse)
async def list_pending_authorizations(
    service: MemberService = Depends(get_member_service),
):
    """The Insurance Agent's work queue: members with an unresolved pending action.

    Covers both `pending` (never started) and `in_progress` (open, possibly awaiting
    a medical director).
    """
    members = service.list_pending_authorizations()
    return {"count": len(members), "members": members}


@router.get("/{member_id}", response_model=Member)
async def get_member(member_id: str, service: MemberService = Depends(get_member_service)):
    """Retrieve a complete member document."""
    doc = service.get_member(member_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return doc


@router.get("/{member_id}/clinical-context", response_model=MemberClinicalContext)
async def get_member_clinical_context(
    member_id: str,
    service: MemberService = Depends(get_member_service),
):
    """Retrieve member's clinical history and eligibility (Phase 1, step 3)."""
    context = service.get_clinical_context(member_id)
    if not context:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return context


@router.post("/{member_id}/treatment-response", response_model=Member)
async def document_treatment_response(
    member_id: str,
    drug: str,
    duration_months: int,
    outcome: str,
    considering_therapy: str,
    notes: str = "",
    service: MemberService = Depends(get_member_service),
):
    """Phase 1, step 1: document a treatment response (EHR integration write).

    Appends the assessment, discontinues the drug, records the considered therapy.
    Returns the updated member.
    """
    member = service.document_treatment_response(
        member_id=member_id,
        drug=drug,
        duration_months=duration_months,
        outcome=outcome,
        notes=notes,
        considering_therapy=considering_therapy,
    )
    if not member:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return member


@router.post("/{member_id}/gap-resolution", response_model=Member)
async def resolve_refill_gap(
    member_id: str,
    drug: str,
    effective_trial_months: int,
    conclusion: str,
    related_note: str = "",
    service: MemberService = Depends(get_member_service),
):
    """Phase 2, step 2: attach the verification agent's gap conclusion.

    Persists the agent-authored `conclusion` as a treatment_response. Returns the
    updated member.
    """
    member = service.resolve_refill_gap(
        member_id=member_id,
        drug=drug,
        effective_trial_months=effective_trial_months,
        conclusion=conclusion,
        related_note=related_note or None,
    )
    if not member:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return member


@router.post("/{member_id}/pending-action", response_model=PendingActionUpdateResponse)
async def update_pending_action(
    member_id: str,
    action_id: str,
    status: str,
    linked_audit_trace_id: str = None,
    service: MemberService = Depends(get_member_service),
):
    """Insurance Agent, steps 0 and 9: advance a pending action's lifecycle.

    `in_progress` at the start of a case, `resolved` only once it has closed. An
    escalated case stays `in_progress` with `linked_audit_trace_id` attached, so the
    frontend shows "awaiting medical director" rather than "not started".
    """
    try:
        return service.update_pending_action(
            member_id=member_id,
            action_id=action_id,
            status=status,
            linked_audit_trace_id=linked_audit_trace_id or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{member_id}/summary", response_model=MemberSummaryResponse)
async def update_member_summary(
    member_id: str,
    last_authorization_status: str = None,
    open_authorization_delta: int = 0,
    service: MemberService = Depends(get_member_service),
):
    """Insurance Agent, step 9: refresh the member's rolling summary after closure.

    Counts are **derived from the member's decision traces**, not incremented. Two
    code paths write these fields — this endpoint and the care-coordination path's
    trace processing — and a delta assumes a single writer, so deriving them means
    the two cannot drift apart.

    `open_authorization_delta` is accepted for compatibility with the agent tool's
    signature and is ignored; `last_authorization_status` acts as an override when
    supplied, and is otherwise derived too.
    """
    result = service.recompute_summary(
        member_id, last_authorization_status=last_authorization_status
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return result


@router.get("", response_model=Union[MemberList, list])
async def list_members(
    policy_id: str = None, service: MemberService = Depends(get_member_service)
):
    """List members, optionally filtered by policy."""
    if policy_id:
        members = service.get_members_by_policy(policy_id)
        return {"count": len(members), "members": members}
    members = service.list_all_members()
    return {"count": len(members), "members": members}
