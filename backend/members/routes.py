"""API routes for member operations."""

from fastapi import APIRouter, Depends, HTTPException
from typing import Union

from db.mdb import MongoDBConnector, get_connector
from .service import MemberService
from .models import Member, MemberClinicalContext, MemberList

router = APIRouter(prefix="/api/members", tags=["members"])


def get_member_service(connector: MongoDBConnector = Depends(get_connector)) -> MemberService:
    return MemberService(connector)


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
    agent: str = None,
    service: MemberService = Depends(get_member_service),
):
    """Retrieve member's clinical history and eligibility.

    Pass `agent` (e.g. `pathway_agent`) to record the read in the audit trail
    (step 3a). Omit it for non-agent reads (UI/inspection) that shouldn't be logged.
    """
    context = service.get_clinical_context(member_id, agent=agent)
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

    Appends the assessment, discontinues the drug, records the considered therapy,
    and logs the audit entry. Returns the updated member.
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

    Persists the agent-authored `conclusion` as a treatment_response and logs the
    `resolve refill gap` audit (citing the explaining note via `related_note`).
    Returns the updated member.
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


@router.get("", response_model=Union[MemberList, list])
async def list_members(
    plan_id: str = None, service: MemberService = Depends(get_member_service)
):
    """List members, optionally filtered by plan."""
    if plan_id:
        members = service.get_members_by_plan(plan_id)
        return {"count": len(members), "members": members}
    members = service.list_all_members()
    return {"count": len(members), "members": members}
