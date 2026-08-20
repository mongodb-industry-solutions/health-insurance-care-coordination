"""Pydantic models for guidelines domain."""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List


def _stringify_id(value):
    """Render a guideline's `_id` as a string, whatever type it is.

    Under the final data model `_id` is a MongoDB-assigned ObjectId, not the
    `CMG-RA-2026.3`-style business string an earlier revision used. Both shapes
    still exist in the wild, so coerce rather than type-pin: a bare `str`
    annotation rejects an ObjectId outright and fails the whole response.
    """
    if value is None or isinstance(value, str):
        return value
    return str(value)


class Criteria(BaseModel):
    step_therapy: Optional[Dict[str, Any]] = None
    coverage_tier: str
    confidence_thresholds: Optional[Dict[str, float]] = None


class GuidelineResponse(BaseModel):
    guideline_id: Optional[str] = Field(default=None, alias="guideline_id")
    condition: str
    effective_date: str
    classification: Dict[str, Any]
    criteria: Criteria
    confidence_threshold: float

    _coerce_id = field_validator("guideline_id", mode="before")(_stringify_id)


class Guideline(BaseModel):
    guideline_id: Optional[str] = Field(default=None, alias="_id")
    condition: str
    effective_date: str
    classification: Dict[str, Any]
    criteria: Criteria
    confidence_threshold: float

    _coerce_id = field_validator("guideline_id", mode="before")(_stringify_id)

    class Config:
        populate_by_name = True


class RecommendationResponse(BaseModel):
    """Step 7: the aggregated confidence and the proposed decision.

    A recommendation, never a closure. `meets_threshold` reports whether the aggregate
    clears the guideline's bar; it does not say who is allowed to close the case, which
    is the separate bounded-authority check in Step 8.
    """
    condition: str
    guideline_ref: str
    step_confidences: List[float] = []
    # The arithmetic spelled out, e.g. "min(0.98, 0.97, 0.95, 0.9) = 0.9 - 0.55
    # (criteria not met) = 0.35". Carried so the trace shows how the number was reached
    # rather than only the number.
    aggregation: str
    weakest_step_confidence: float
    clinical_failure_penalty_applied: bool
    confidence: float
    confidence_threshold: Optional[float] = None
    meets_threshold: bool
    criteria_satisfied: bool
    coverage_restriction: str
    recommendation: str  # approved | approved_restricted | denied
    rationale: str
    detail: str


class StepTherapyResponse(BaseModel):
    """Step 6 (procedural memory): the guideline's step-therapy gate applied.

    `satisfied` is the outcome, but it is an input to the recommendation rather than a
    decision — a failure here never closes the case on its own.
    """
    condition: str
    guideline_ref: str
    # Null only when the condition's guideline sets no step-therapy requirement.
    required_drug: Optional[str] = None
    required_months: float
    documented_drug: Optional[str] = None
    documented_months: float
    step_therapy_applies: bool
    # Null when no requirement applies; False means the documented trial is of a
    # different drug, which fails for a different reason than being too short.
    drug_matches: Optional[bool] = None
    satisfied: bool
    confidence_threshold: Optional[float] = None
    confidence: float
    detail: str


class ClassificationResponse(BaseModel):
    """Step 4 (taxonomic memory): the requested treatment placed in its category.

    `inferred` is the field that matters: False means the guideline named this drug,
    True means only its tier could be derived from the condition. The confidence
    difference between the two is what carries that distinction downstream.
    """
    condition: str
    guideline_ref: str
    therapy: str
    classified: bool
    inferred: bool
    # Null when the drug is not enumerated — no reference data names its class, and
    # guessing one would be inventing taxonomy.
    treatment_class: Optional[str] = None
    tier: Optional[str] = None
    prior_auth_required: bool
    # The gate Steps 5 and 6 go on to evaluate.
    step_therapy_applies: bool
    step_therapy_drug: Optional[str] = None
    # Float to match `required_months` on the step-therapy response: both surface the
    # same guideline value, and typing them differently means a guideline with a
    # fractional minimum would validate on one endpoint and 500 on the other.
    step_therapy_min_months: Optional[float] = None
    # The bar the aggregate confidence is checked against in Step 8.
    confidence_threshold: Optional[float] = None
    confidence: float
    detail: str


class GuidelinesListResponse(BaseModel):
    condition: str
    count: int
    guidelines: List[Guideline]


class AllGuidelinesResponse(BaseModel):
    count: int
    guidelines: List[Guideline]
