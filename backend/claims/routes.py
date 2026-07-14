"""API routes for claims operations."""

from fastapi import APIRouter, HTTPException

from .service import ClaimService

router = APIRouter(prefix="/api/claims", tags=["claims"])
service = ClaimService()


@router.get("/comparable")
async def find_comparable_claims(service_name: str, diagnosis: str):
    """Find prior adjudicated claims with the same service and diagnosis.

    Used as episodic memory: shows precedent of similar treatments for
    similar presentations.
    """
    claims = service.find_comparable_cases(service_name, diagnosis)
    return {
        "query": {"service": service_name, "diagnosis": diagnosis},
        "count": len(claims),
        "claims": claims,
    }


@router.get("/member/{member_id}")
async def get_member_claims(member_id: str):
    """Retrieve all claims for a member."""
    claims = service.get_member_claims(member_id)
    return {
        "member_id": member_id,
        "claim_count": len(claims),
        "claims": claims,
    }


@router.get("/{claim_id}")
async def get_claim(claim_id: str):
    """Retrieve a specific claim."""
    doc = service.get_claim(claim_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    return doc


@router.get("")
async def list_all_claims():
    """Retrieve all claims."""
    return service.list_all_claims()
