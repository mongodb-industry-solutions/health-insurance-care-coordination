"""API routes for plan operations."""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_insurance_connector
from .service import PlanService
from .models import Plan, PlansListResponse

router = APIRouter(prefix="/api/plans", tags=["plans"])


def get_plan_service(
    connector: MongoDBConnector = Depends(get_insurance_connector),
) -> PlanService:
    return PlanService(connector)


@router.get("/{plan_id}", response_model=Plan)
async def get_plan(plan_id: str, service: PlanService = Depends(get_plan_service)):
    """Retrieve a plan."""
    doc = service.get_plan(plan_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    return doc


@router.get("", response_model=PlansListResponse)
async def list_all_plans(service: PlanService = Depends(get_plan_service)):
    """Retrieve all plans."""
    plans = service.list_all_plans()
    return {"count": len(plans), "plans": plans}
