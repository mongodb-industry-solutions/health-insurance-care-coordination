"""API routes for plan operations."""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_connector
from .service import PlanService
from .models import CoverageCheckResponse, Plan, PlansListResponse

router = APIRouter(prefix="/api/plans", tags=["plans"])


def get_plan_service(connector: MongoDBConnector = Depends(get_connector)) -> PlanService:
    return PlanService(connector)


@router.get("/{plan_id}", response_model=Plan)
async def get_plan(plan_id: str, service: PlanService = Depends(get_plan_service)):
    """Retrieve a plan."""
    doc = service.get_plan(plan_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    return doc


@router.get("/{plan_id}/coverage", response_model=CoverageCheckResponse)
async def check_treatment_coverage(
    plan_id: str,
    condition: str,
    treatment_code: str = None,
    drug: str = None,
    service: PlanService = Depends(get_plan_service),
):
    """Insurance Agent, step 2: does the plan cover this treatment, and which stages?

    The second administrative gate. Identify the treatment by `treatment_code`
    (preferred, exact) or by `drug` name; `condition` is required either way,
    because a treatment code is listed once per condition it applies to and so is
    not unique on its own.

    `covered: false` stops the process before clinical review — the agent closes it
    as a benefit exclusion. `restriction: "partial"` proceeds to clinical review but
    caps the outcome at `approved_restricted`.
    """
    try:
        result = service.check_treatment_coverage(
            plan_id, condition=condition, treatment_code=treatment_code, drug=drug
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    return result


@router.get("", response_model=PlansListResponse)
async def list_all_plans(service: PlanService = Depends(get_plan_service)):
    """Retrieve all plans."""
    plans = service.list_all_plans()
    return {"count": len(plans), "plans": plans}
