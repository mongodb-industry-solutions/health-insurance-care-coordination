"""API routes for authorization operations."""

from fastapi import APIRouter, HTTPException

from .service import AuthorizationService

router = APIRouter(prefix="/api/authorizations", tags=["authorizations"])
service = AuthorizationService()


@router.get("/{auth_id}")
async def get_authorization(auth_id: str):
    """Retrieve a specific authorization."""
    doc = service.get_authorization(auth_id)
    if not doc:
        raise HTTPException(
            status_code=404, detail=f"Authorization {auth_id} not found"
        )
    return doc


@router.post("/evaluate")
async def evaluate_authorization(
    member_id: str,
    requested_service: str,
    diagnosis_code: str,
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


@router.get("/member/{member_id}")
async def get_member_authorizations(member_id: str):
    """Retrieve all authorizations for a member."""
    auths = service.get_member_authorizations(member_id)
    return {
        "member_id": member_id,
        "authorization_count": len(auths),
        "authorizations": auths,
    }


@router.get("/pending-review/list")
async def get_pending_human_review():
    """Retrieve all authorizations pending medical director review."""
    auths = service.get_pending_human_review()
    return {
        "count": len(auths),
        "authorizations": auths,
    }
