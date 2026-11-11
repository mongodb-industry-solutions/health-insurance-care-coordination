"""API routes for claims operations."""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_insurance_connector
from .service import ClaimService
from .models import MemberClaimsResponse, PrecedentSummary, RefillGapsResponse

router = APIRouter(prefix="/api/claims", tags=["claims"])


def get_claim_service(
    connector: MongoDBConnector = Depends(get_insurance_connector),
) -> ClaimService:
    return ClaimService(connector)


@router.get("/precedent", response_model=PrecedentSummary)
async def precedent(
    procedure_code: str,
    diagnosis_code: str = None,
    member_id: str = None,
    service: ClaimService = Depends(get_claim_service),
):
    """What other members' approved claims for this procedure cost: the reference price
    behind the cost estimator.

    Statistics only (median, min, max of billed, paid and member-owed, and how many claims
    they rest on). No member or claim identifiers are returned. Pass `member_id` to leave
    that member's own claims out.
    """
    try:
        return service.precedent_summary(procedure_code, diagnosis_code, exclude_member=member_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
