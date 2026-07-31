"""Pydantic models for plans domain.

The Plan holds coverage rules with benefits embedded directly — no separate
benefit-schedule object — and is reusable across many Policies. Coverage is
organized by tier (standard vs. specialty); the specialty tier is where
prior-authorization and step-therapy-driven decisions apply.

Cost-share note: `coinsurance` (a percentage of cost) and `copay` (a flat dollar
amount) are both optional per tier so either plan style can be represented; the
unused one is left null. These fields are modeled for realism only — the demo
runs the prior-auth *decision*, not claims-adjudication math.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List


class TierCoverage(BaseModel):
    covered: bool
    prior_auth_required: bool = Field(alias="priorAuthRequired")
    # Cost-share (modeled, not computed). One of coinsurance/copay is typically set.
    coinsurance: Optional[float] = None
    copay: Optional[float] = None
    deductible: Optional[float] = None
    out_of_pocket_max: Optional[float] = Field(default=None, alias="outOfPocketMax")

    class Config:
        populate_by_name = True


class Coverage(BaseModel):
    tiers: Dict[str, TierCoverage]
    excluded_services: List[str] = Field(default=[], alias="excludedServices")

    class Config:
        populate_by_name = True


class EligibilityRules(BaseModel):
    requires_active_status: bool = Field(default=True, alias="requiresActiveStatus")

    class Config:
        populate_by_name = True


class TreatmentStep(BaseModel):
    """One funded step of a treatment protocol (e.g. baseline labs, loading dose).

    Cost-share is modeled per step for realism; the demo runs no adjudication math.
    """
    step_code: str = Field(alias="stepCode")
    step_name: Optional[str] = Field(default=None, alias="stepName")
    covered: bool = True
    coinsurance: Optional[float] = None
    copay: Optional[float] = None

    class Config:
        populate_by_name = True


class Treatment(BaseModel):
    """A specific treatment the plan covers and the steps it pays for.

    Keyed by `drug` (+ `condition`) so a coverage check can resolve directly from
    how the agent names the considered therapy, rather than string-matching display
    names. `treatment_code` (a J-code) also lines up with `claims.procedureCode`.
    """
    treatment_code: Optional[str] = Field(default=None, alias="treatmentCode")
    treatment_name: Optional[str] = Field(default=None, alias="treatmentName")
    drug: str                       # lookup key, e.g. "secukinumab"
    rxnorm: Optional[str] = None
    condition: Optional[str] = None  # ICD-10 the treatment applies to
    tier: Optional[str] = None
    covered: bool = True
    prior_auth_required: bool = Field(default=True, alias="priorAuthRequired")
    steps: List[TreatmentStep] = []

    class Config:
        populate_by_name = True


class Plan(BaseModel):
    plan_id: str = Field(alias="_id")
    plan_name: Optional[str] = Field(default=None, alias="planName")
    plan_type: Optional[str] = Field(default=None, alias="planType")
    network: Optional[str] = None
    jurisdiction: Optional[str] = None
    eligibility_rules: Optional[EligibilityRules] = Field(default=None, alias="eligibilityRules")
    coverage: Optional[Coverage] = None
    # Per-plan covered treatments + the protocol steps the plan pays for. A
    # treatment-level coverage check keys off `drug` + `condition`; falls back to
    # tier-level coverage when a therapy has no explicit treatment entry.
    treatments: List[Treatment] = []
    effective_date: Optional[str] = Field(default=None, alias="effectiveDate")
    renewal_date: Optional[str] = Field(default=None, alias="renewalDate")
    schema_version: Optional[str] = Field(default=None, alias="schemaVersion")
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")

    class Config:
        populate_by_name = True


class PlansListResponse(BaseModel):
    count: int
    plans: List[Plan]
