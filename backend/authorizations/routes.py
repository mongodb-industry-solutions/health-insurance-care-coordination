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


@router.post("/evaluate", response_model=Authorization)
async def evaluate_authorization(
    member_id: str,
    requested_service: str,
    diagnosis_code: str,
    service: AuthorizationService = Depends(get_authorization_service),
):
    """Evaluate an authorization request.

    This is the main entry point for authorization decisions. It orchestrates:
    - Member clinical context retrieval
    - Applicable guideline lookup
    - Step therapy validation
    - Comparable case retrieval
    - Decision trace assembly (CMS compliance)
    - Audit logging
    """
    try:
        auth = service.evaluate_authorization(
            member_id=member_id,
            requested_service=requested_service,
            diagnosis_code=diagnosis_code,
        )
        return auth
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
