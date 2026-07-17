"""API routes for authorization operations."""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_connector
from .service import AuthorizationService
from .models import Authorization, MemberAuthorizationsResponse, PendingReviewResponse

router = APIRouter(prefix="/api/authorizations", tags=["authorizations"])


def get_authorization_service(
    connector: MongoDBConnector = Depends(get_connector),
) -> AuthorizationService:
    return AuthorizationService(connector)


@router.get("/{auth_id}", response_model=Authorization)
async def get_authorization(
    auth_id: str, service: AuthorizationService = Depends(get_authorization_service)
):
    """Retrieve a specific authorization."""
    doc = service.get_authorization(auth_id)
    if not doc:
        raise HTTPException(
            status_code=404, detail=f"Authorization {auth_id} not found"
        )
    return doc


@router.post("/file", response_model=Authorization)
async def file_authorization(
    member_id: str,
    requested_service: str,
    service: AuthorizationService = Depends(get_authorization_service),
):
    """Phase 3, step 1: file a formal authorization request.

    Creates a `pending` authorization (no decision yet) and logs `authorization
    filed`. This is the provider/EHR filing the request; processing/deciding it
    is a later step.
    """
    try:
        return service.file_authorization(
            member_id=member_id, requested_service=requested_service
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/process", response_model=Authorization)
async def process_authorization(
    member_id: str,
    service: AuthorizationService = Depends(get_authorization_service),
):
    """Phase 3, step 2: process the member's pending authorization.

    Deterministically computes the decision from the member's current record, the
    guideline, and comparable precedent; populates the decision_trace with a
    computed confidence; applies bounded authority; recomputes the member summary;
    and audits the decision.
    """
    try:
        return service.process_authorization(member_id=member_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/member/{member_id}", response_model=MemberAuthorizationsResponse)
async def get_member_authorizations(
    member_id: str, service: AuthorizationService = Depends(get_authorization_service)
):
    """Retrieve all authorizations for a member."""
    auths = service.get_member_authorizations(member_id)
    return {
        "member_id": member_id,
        "authorization_count": len(auths),
        "authorizations": auths,
    }


@router.get("/pending-review/list", response_model=PendingReviewResponse)
async def get_pending_human_review(
    service: AuthorizationService = Depends(get_authorization_service),
):
    """Retrieve all authorizations pending medical director review."""
    auths = service.get_pending_human_review()
    return {
        "count": len(auths),
        "authorizations": auths,
    }


@router.get("/{auth_id}/review")
async def open_human_review(
    auth_id: str,
    medical_director_id: str = None,
    service: AuthorizationService = Depends(get_authorization_service),
):
    """Phase 3a, step 2: assemble the brief for a medical director (full
    authorization + broader member context). Pass `medical_director_id` to log
    `human review opened` (2a).
    """
    try:
        return service.open_human_review(auth_id, medical_director_id=medical_director_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{auth_id}/close", response_model=Authorization)
async def close_authorization(
    auth_id: str,
    medical_director_id: str,
    decision: str,
    notes: str = "",
    service: AuthorizationService = Depends(get_authorization_service),
):
    """Phase 3a, step 3: a medical director sets the final decision on a routed
    authorization (`decision`: `approved` or `denied`). Only routed cases can be
    human-closed — the agent never issues the final denial.
    """
    try:
        return service.close_authorization(
            auth_id, medical_director_id=medical_director_id,
            decision=decision, notes=notes or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
