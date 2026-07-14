"""API routes for guidelines operations."""

from fastapi import APIRouter, HTTPException

from .service import GuidelineService

router = APIRouter(prefix="/api/guidelines", tags=["guidelines"])
service = GuidelineService()


@router.get("/condition/{condition_code}")
async def get_guideline_for_condition(condition_code: str):
    """Retrieve the latest guideline for a condition.

    Returns taxonomic classification and procedural criteria that agents
    use to evaluate medical necessity.
    """
    guideline = service.get_guideline_for_condition(condition_code)
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


@router.get("/condition/{condition_code}/all")
async def get_all_guidelines_for_condition(condition_code: str):
    """Retrieve all guideline versions for a condition (newest first)."""
    guidelines = service.get_all_guidelines_for_condition(condition_code)
    return {
        "condition": condition_code,
        "count": len(guidelines),
        "guidelines": guidelines,
    }


@router.get("/{guideline_id}")
async def get_guideline(guideline_id: str):
    """Retrieve a specific guideline by ID."""
    doc = service.get_guideline(guideline_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Guideline {guideline_id} not found")
    return doc


@router.get("")
async def list_all_guidelines():
    """Retrieve all guidelines."""
    return service.list_all_guidelines()
