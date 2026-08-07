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
    member_id: str = None,
    service: ClaimService = Depends(get_claim_service),
):
    """Find comparable precedent — other members' approved claims for the same
    service and diagnosis (episodic memory).

    Pass `member_id` to exclude the member from their own results.
    """
    claims = service.find_comparable_cases(
        service_name, diagnosis, member_id=member_id
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
    service: ClaimService = Depends(get_claim_service),
):
    """Step 5b: detect breaks in medication refill cadence from the pharmacy
    claims."""
    return service.detect_refill_gaps(member_id, drug=drug)


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


@router.post("", response_model=Claim)
async def create_claim(
    member_id: str,
    procedure_code: str,
    procedure_desc: str,
    diagnosis_code: str,
    diagnosis_display: str,
    billed_amt: float,
    claim_type: str = "specialty_pharmacy",
    service_date: str = None,
    service: ClaimService = Depends(get_claim_service),
):
    """Insurance Agent, step 0: open a claim for a requested service.

    Opens in `pending` status with a server-generated `claimId`. `policyId` and the
    treating provider are resolved from the member record, not taken from the
    caller. Nothing is decided here.
    """
    try:
        return service.create_claim(
            member_id=member_id,
            procedure_code=procedure_code,
            procedure_desc=procedure_desc,
            diagnosis_code=diagnosis_code,
            diagnosis_display=diagnosis_display,
            billed_amt=billed_amt,
            claim_type=claim_type,
            service_date=service_date,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{claim_id}/status", response_model=Claim)
async def update_claim_status(
    claim_id: str,
    status: str,
    paid_amt: float = 0,
    member_owed: float = 0,
    denial_reason: str = None,
    linked_audit_trace_id: str = None,
    service: ClaimService = Depends(get_claim_service),
):
    """Insurance Agent, step 9: apply a reached decision to its claim.

    Guardrail: a claim cannot be set to `approved`, `approved_restricted` or `paid`
    while its linked decision trace records a denial or is still undecided. A 400
    here means that guardrail fired — resolve the trace rather than retrying.
    """
    try:
        return service.update_claim_status(
            claim_id=claim_id,
            status=status,
            paid_amt=paid_amt,
            member_owed=member_owed,
            denial_reason=denial_reason,
            linked_audit_trace_id=linked_audit_trace_id,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
