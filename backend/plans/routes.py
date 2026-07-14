"""API routes for plan operations."""

from fastapi import APIRouter, HTTPException

from .service import PlanService

router = APIRouter(prefix="/api/plans", tags=["plans"])
service = PlanService()


@router.get("/{plan_id}")
async def get_plan(plan_id: str):
    """Retrieve a plan."""
    doc = service.get_plan(plan_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    return doc


@router.get("")
async def list_all_plans():
    """Retrieve all plans."""
    return service.list_all_plans()
