"""Pydantic models for guidelines domain."""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List


class Criteria(BaseModel):
    step_therapy: Optional[Dict[str, Any]] = None
    coverage_tier: str
    confidence_thresholds: Optional[Dict[str, float]] = None


class GuidelineResponse(BaseModel):
    guideline_id: str = Field(alias="guideline_id")
    condition: str
    effective_date: str
    classification: Dict[str, Any]
    criteria: Criteria
    confidence_threshold: float


class Guideline(BaseModel):
    guideline_id: str = Field(alias="_id")
    condition: str
    effective_date: str
    classification: Dict[str, Any]
    criteria: Criteria
    confidence_threshold: float

    class Config:
        populate_by_name = True


class GuidelinesListResponse(BaseModel):
    condition: str
    count: int
    guidelines: List[Guideline]


class AllGuidelinesResponse(BaseModel):
    count: int
    guidelines: List[Guideline]
