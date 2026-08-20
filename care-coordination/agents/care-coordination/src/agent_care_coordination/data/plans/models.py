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
    # Null when the tier is not covered at all: an uncovered tier has no
    # prior-auth question to answer, and False would read as "covered without
    # prior auth".
    prior_auth_required: Optional[bool] = Field(default=None, alias="priorAuthRequired")
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

    Keyed by `treatment_code` + `condition`. Neither alone is unique: the same
    code appears once per condition it applies to (e.g. methotrexate `6851` under
    both `M06.9` and `L40.50`), so a coverage check must match on both.
    `treatment_code` also lines up with `claims.procedureCode`.

    `drug` is a legacy lookup key that the final data model dropped in favour of
    `treatment_code`; it is optional because live documents do not carry it.
    Resolving a therapy the agent named in prose (e.g. "secukinumab") goes through
    `treatment_name` instead — see `PlanService.check_treatment_coverage`.
    """
    treatment_code: Optional[str] = Field(default=None, alias="treatmentCode")
    treatment_name: Optional[str] = Field(default=None, alias="treatmentName")
    drug: Optional[str] = None      # legacy lookup key; absent in the final model
    rxnorm: Optional[str] = None
    condition: Optional[str] = None  # ICD-10 the treatment applies to
    tier: Optional[str] = None
    covered: bool = True
    # Null on an uncovered treatment — see the note on `TierCoverage`.
    prior_auth_required: Optional[bool] = Field(default=True, alias="priorAuthRequired")
    steps: List[TreatmentStep] = []

    class Config:
        populate_by_name = True


class Plan(BaseModel):
    plan_id: str = Field(alias="planId")
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


class CoverageCheckResponse(BaseModel):
    """Result of the second administrative gate — does the plan cover this
    treatment, and which stages of it? (Insurance Agent, step 2.)

    Three outcomes matter to the caller:

    - `covered: false` stops the process. No clinical review runs, and the agent
      closes the case itself as a benefit-exclusion determination.
    - `restriction: "partial"` means some stages of the protocol are funded and
      others are not. The case still goes to clinical review, but its eventual
      outcome must be `approved_restricted`, never a plain approval — the member
      carries the cost of `uncovered_steps`.
    - `covered: true` with `restriction: "none"` is a clean pass to clinical
      review, gated on `prior_auth_required`.
    """
    covered: bool
    # none | partial when covered; null when not covered.
    restriction: Optional[str] = None
    # stepCode values, split by whether the plan funds that stage.
    covered_steps: List[str] = Field(default=[], alias="coveredSteps")
    uncovered_steps: List[str] = Field(default=[], alias="uncoveredSteps")
    # Null when the treatment is not covered at all: prior authorization is moot
    # for a benefit the plan does not provide.
    prior_auth_required: Optional[bool] = Field(default=None, alias="priorAuthRequired")
    # treatment_not_listed_for_condition | benefit_exclusion | no_steps_covered
    reason: Optional[str] = None
    tier: Optional[str] = None
    plan_id: str = Field(alias="planId")
    treatment_code: Optional[str] = Field(default=None, alias="treatmentCode")
    treatment_name: Optional[str] = Field(default=None, alias="treatmentName")
    condition: Optional[str] = None
    # How the treatments[] entry was resolved: "treatment_code" is exact,
    # "treatment_name" is a substring match on prose and is reflected in a lower
    # confidence. Null when nothing matched.
    matched_on: Optional[str] = Field(default=None, alias="matchedOn")
    confidence: float
    detail: str

    class Config:
        populate_by_name = True
