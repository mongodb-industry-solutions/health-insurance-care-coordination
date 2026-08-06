"""API routes for member operations."""

from fastapi import APIRouter, Depends, HTTPException
from typing import Union

from db.mdb import MongoDBConnector, get_connector
from .service import MemberService
from .models import (
    Member,
    MemberClinicalContext,
    MemberList,
    ConceptMatchResponse,
    OpenCaseResponse,
    TrialHistoryResponse,
)

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
    service: MemberService = Depends(get_member_service),
):
    """Retrieve member's clinical history and eligibility (Phase 1, step 3)."""
    context = service.get_clinical_context(member_id)
    if not context:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return context


@router.get("/{member_id}/open-case", response_model=OpenCaseResponse)
async def get_open_case(
    member_id: str,
    service: MemberService = Depends(get_member_service),
):
    """The member's open pending action — a downstream agent's entry point.

    The agents in this workflow coordinate through the record rather than by
    calling each other: one opens the case, another reads it back. Returns the
    requested therapy and the trace to append reasoning to. Read-only.
    """
    result = service.get_open_case(member_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return result


@router.get("/{member_id}/trial-history", response_model=TrialHistoryResponse)
async def review_trial_history(
    member_id: str,
    drug: str,
    cadence_days: int = 30,
    gap_factor: float = 1.5,
    service: MemberService = Depends(get_member_service),
):
    """Step 5: review the member's trial of the required therapy.

    Episodic memory. Derives the effective trial duration from pharmacy fills, flags
    any interruption, and reports whether documentation explains it. An unexplained
    interruption credits only the longest uninterrupted run and lowers confidence.
    Read-only — use `/gap-resolution` to persist a conclusion.
    """
    result = service.review_trial_history(
        member_id=member_id, drug=drug, cadence_days=cadence_days, gap_factor=gap_factor
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return result


@router.get("/{member_id}/concept-match", response_model=ConceptMatchResponse)
async def match_clinical_concept(
    member_id: str,
    requested_treatment: str,
    service: MemberService = Depends(get_member_service),
):
    """Step 3: match a requested therapy to a documented condition.

    Semantic memory. The provider names a drug; the record carries ICD-10 codes.
    Resolves one to the other through the guideline that classifies the drug, and
    returns a confidence-scored match. Read-only — nothing is written here.
    """
    result = service.match_clinical_concept(
        member_id=member_id, requested_treatment=requested_treatment
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return result


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
