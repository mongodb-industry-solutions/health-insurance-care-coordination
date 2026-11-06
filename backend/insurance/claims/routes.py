"""API routes for claims operations."""

from fastapi import APIRouter, Depends

from db.mdb import MongoDBConnector, get_insurance_connector
from .service import ClaimService
from .models import MemberClaimsResponse, RefillGapsResponse

router = APIRouter(prefix="/api/claims", tags=["claims"])


def get_claim_service(
    connector: MongoDBConnector = Depends(get_insurance_connector),
) -> ClaimService:
    return ClaimService(connector)


@router.get("/member/{member_id}", response_model=MemberClaimsResponse)
async def get_member_claims(
    member_id: str, service: ClaimService = Depends(get_claim_service)
):
    """Retrieve all claims for a member."""
    claims = service.get_member_claims(member_id)
    return {
        "member_id": member_id,
        "claim_count": len(claims),
        "claims": claims,
    }


@router.get("/member/{member_id}/refill-gaps", response_model=RefillGapsResponse)
async def detect_refill_gaps(
    member_id: str,
    drug: str = None,
    service: ClaimService = Depends(get_claim_service),
):
    """Detect breaks in medication refill cadence from the pharmacy claims."""
    return service.detect_refill_gaps(member_id, drug=drug)
