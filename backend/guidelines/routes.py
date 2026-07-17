"""API routes for guidelines operations."""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_connector
from .service import GuidelineService
from .models import GuidelineResponse, Guideline, GuidelinesListResponse, AllGuidelinesResponse

router = APIRouter(prefix="/api/guidelines", tags=["guidelines"])


def get_guideline_service(
    connector: MongoDBConnector = Depends(get_connector),
) -> GuidelineService:
    return GuidelineService(connector)


@router.get("/condition/{condition_code}", response_model=GuidelineResponse)
async def get_guideline_for_condition(
    condition_code: str,
    agent: str = None,
    member_id: str = None,
    service: GuidelineService = Depends(get_guideline_service),
):
    """Retrieve the latest guideline for a condition.

    Returns taxonomic classification and procedural criteria that agents
    use to evaluate medical necessity. Pass both `agent` and `member_id` to
    record the read in that member's audit trail (step 4a).
    """
    guideline = service.get_guideline_for_condition(
        condition_code, agent=agent, member_id=member_id
    )
    if not guideline:
        raise HTTPException(
            status_code=404,
            detail=f"No guideline found for condition {condition_code}",
        )
    return {
        "guideline_id": guideline.get("_id"),
        "condition": guideline.get("condition"),
        "effective_date": guideline.get("effective_date"),
        "classification": guideline.get("classification"),
        "criteria": guideline.get("criteria"),
        "confidence_threshold": guideline.get("confidence_threshold"),
    }


@router.get("/condition/{condition_code}/all", response_model=GuidelinesListResponse)
async def get_all_guidelines_for_condition(
    condition_code: str, service: GuidelineService = Depends(get_guideline_service)
):
    """Retrieve all guideline versions for a condition (newest first)."""
    guidelines = service.get_all_guidelines_for_condition(condition_code)
    return {
        "condition": condition_code,
        "count": len(guidelines),
        "guidelines": guidelines,
    }


@router.get("/{guideline_id}", response_model=Guideline)
async def get_guideline(
    guideline_id: str, service: GuidelineService = Depends(get_guideline_service)
):
    """Retrieve a specific guideline by ID."""
    doc = service.get_guideline(guideline_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Guideline {guideline_id} not found")
    return doc


@router.get("", response_model=AllGuidelinesResponse)
async def list_all_guidelines(service: GuidelineService = Depends(get_guideline_service)):
    """Retrieve all guidelines."""
    guidelines = service.list_all_guidelines()
    return {"count": len(guidelines), "guidelines": guidelines}
