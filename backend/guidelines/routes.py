"""API routes for guidelines operations."""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_connector
from .service import GuidelineService
from .models import (
    GuidelineResponse,
    Guideline,
    GuidelinesListResponse,
    AllGuidelinesResponse,
    ClassificationResponse,
    StepTherapyResponse,
    RecommendationResponse,
)

router = APIRouter(prefix="/api/guidelines", tags=["guidelines"])


def get_guideline_service(
    connector: MongoDBConnector = Depends(get_connector),
) -> GuidelineService:
    return GuidelineService(connector)


@router.get("/condition/{condition_code}", response_model=GuidelineResponse)
async def get_guideline_for_condition(
    condition_code: str,
    service: GuidelineService = Depends(get_guideline_service),
):
    """Retrieve the latest guideline for a condition.

    Returns taxonomic classification and procedural criteria that agents use to
    evaluate medical necessity.
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


@router.get("/condition/{condition_code}/classify", response_model=ClassificationResponse)
async def classify_treatment(
    condition_code: str,
    requested_treatment: str,
    service: GuidelineService = Depends(get_guideline_service),
):
    """Step 4: classify a requested treatment against the condition's guideline.

    Taxonomic memory. Returns the treatment's class, tier and prior-auth status, and
    whether step-therapy criteria apply. A drug the guideline does not enumerate is
    still classified by category, with `inferred: true` and reduced confidence.
    Read-only.
    """
    result = service.classify_treatment(
        condition_code=condition_code, requested_treatment=requested_treatment
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"No guideline found for condition {condition_code}"
        )
    return result


@router.get("/condition/{condition_code}/step-therapy", response_model=StepTherapyResponse)
async def evaluate_step_therapy(
    condition_code: str,
    documented_drug: str,
    documented_months: float,
    service: GuidelineService = Depends(get_guideline_service),
):
    """Step 6: apply the condition's step-therapy criteria to a documented trial.

    Procedural memory. Returns satisfied / not satisfied, distinguishing a trial that
    is too short from one that is of the wrong drug entirely. A failure here is an
    input to the recommendation, never a closure. Read-only.
    """
    result = service.evaluate_step_therapy(
        condition_code=condition_code,
        documented_drug=documented_drug,
        documented_months=documented_months,
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"No guideline found for condition {condition_code}"
        )
    return result


@router.get("/condition/{condition_code}/recommendation", response_model=RecommendationResponse)
async def compute_recommendation(
    condition_code: str,
    step_confidences: str,
    criteria_satisfied: bool,
    coverage_restriction: str = "none",
    service: GuidelineService = Depends(get_guideline_service),
):
    """Step 7: aggregate the step confidences and propose a decision.

    Recommends only — reports whether the aggregate clears the guideline's threshold,
    but never decides who may close the case. Read-only.

    `step_confidences` is a comma-separated list, e.g. `0.98,0.97,0.95,0.90`.
    """
    try:
        parsed = [float(part) for part in step_confidences.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                "step_confidences must be a comma-separated list of numbers, "
                "e.g. '0.98,0.97,0.95,0.90'"
            ),
        )

    result = service.compute_recommendation(
        condition_code=condition_code,
        step_confidences=parsed,
        criteria_satisfied=criteria_satisfied,
        coverage_restriction=coverage_restriction,
    )
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"No guideline found for condition {condition_code}"
        )
    return result


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
