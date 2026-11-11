"""API routes for policy operations."""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_insurance_connector
from .service import PolicyService
from .models import Policy

router = APIRouter(prefix="/api/policies", tags=["policies"])


def get_policy_service(
    connector: MongoDBConnector = Depends(get_insurance_connector),
) -> PolicyService:
    return PolicyService(connector)


@router.get("/{policy_id}", response_model=Policy)
async def get_policy(policy_id: str, service: PolicyService = Depends(get_policy_service)):
    """Retrieve a policy."""
    doc = service.get_policy(policy_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")
    return doc
