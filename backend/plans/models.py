"""Pydantic models for plans domain."""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List


class TierCoverage(BaseModel):
    covered: bool
    prior_auth_required: bool


class Coverage(BaseModel):
    tiers: Dict[str, TierCoverage]
    excluded_services: List[str] = []


class EligibilityRules(BaseModel):
    requires_active_status: bool = True


class Plan(BaseModel):
    plan_id: str = Field(alias="_id")
    name: str
    # Stored as `type` in the document; exposed as `plan_type` on the API.
    plan_type: str = Field(alias="type")
    network: Optional[str] = None
    eligibility_rules: Optional[EligibilityRules] = None
    coverage: Optional[Coverage] = None

    class Config:
        populate_by_name = True


class PlansListResponse(BaseModel):
    count: int
    plans: List[Plan]
