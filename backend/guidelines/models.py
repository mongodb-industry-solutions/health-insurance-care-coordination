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


class GuidelinesListResponse(BaseModel):
    condition: str
    count: int
    guidelines: List[Guideline]


class AllGuidelinesResponse(BaseModel):
    count: int
    guidelines: List[Guideline]
