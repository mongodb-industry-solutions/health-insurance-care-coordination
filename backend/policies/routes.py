"""API routes for policy operations."""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_connector
from .service import PolicyService
from .models import Policy, PoliciesListResponse

router = APIRouter(prefix="/api/policies", tags=["policies"])


def get_policy_service(connector: MongoDBConnector = Depends(get_connector)) -> PolicyService:
    return PolicyService(connector)


@router.get("/{policy_id}", response_model=Policy)
async def get_policy(policy_id: str, service: PolicyService = Depends(get_policy_service)):
    """Retrieve a policy."""
    doc = service.get_policy(policy_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Policy {policy_id} not found")
    return doc


@router.get("", response_model=PoliciesListResponse)
async def list_all_policies(service: PolicyService = Depends(get_policy_service)):
    """Retrieve all policies."""
    policies = service.list_all_policies()
    return {"count": len(policies), "policies": policies}
