"""API routes for claims operations."""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_connector
from .service import ClaimService
from .models import (
    Claim,
    ComparableClaimsResponse,
    MemberClaimsResponse,
    ClaimsList,
    RefillGapsResponse,
)

router = APIRouter(prefix="/api/claims", tags=["claims"])


def get_claim_service(connector: MongoDBConnector = Depends(get_connector)) -> ClaimService:
    return ClaimService(connector)


@router.get("/comparable", response_model=ComparableClaimsResponse)
async def find_comparable_claims(
    service_name: str,
    diagnosis: str,
    agent: str = None,
    member_id: str = None,
    service: ClaimService = Depends(get_claim_service),
):
    """Find comparable precedent — other members' approved claims for the same
    service and diagnosis (episodic memory).

    Pass both `agent` and `member_id` to record the read in that member's audit
    trail (step 6a); `member_id` also excludes the member from their own results.
    """
    claims = service.find_comparable_cases(
        service_name, diagnosis, agent=agent, member_id=member_id
    )
    return {
        "query": {"service": service_name, "diagnosis": diagnosis},
        "count": len(claims),
        "claims": claims,
    }


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
    agent: str = None,
    service: ClaimService = Depends(get_claim_service),
):
    """Phase 2, step 1: detect breaks in medication refill cadence from the
    pharmacy claims. Pass `agent` (e.g. `verification_agent`) to record the
    detection in the audit trail (step 1a).
    """
    return service.detect_refill_gaps(member_id, drug=drug, agent=agent)


@router.get("/{claim_id}", response_model=Claim)
async def get_claim(claim_id: str, service: ClaimService = Depends(get_claim_service)):
    """Retrieve a specific claim."""
    doc = service.get_claim(claim_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    return doc


@router.get("", response_model=ClaimsList)
async def list_all_claims(service: ClaimService = Depends(get_claim_service)):
    """Retrieve all claims."""
    claims = service.list_all_claims()
    return {"count": len(claims), "claims": claims}
