"""Pydantic models for the policies domain.

The Policy is the direct contract between an individual member and the insurer.
It is intentionally lightweight in this demo — billing detail is omitted and
premium reduced to what realism needs, since neither drives the prior-auth story.
One Policy references exactly one Plan (`plan_id`); a single Plan may back many
Policies.
"""

from pydantic import BaseModel, Field
from typing import Optional, List


class EffectivePeriod(BaseModel):
    effective_date: str = Field(alias="effectiveDate")
    expiry_date: Optional[str] = Field(default=None, alias="expiryDate")
    renewal_date: Optional[str] = Field(default=None, alias="renewalDate")

    class Config:
        populate_by_name = True


class Party(BaseModel):
    customer_id: str = Field(alias="customerId")
    role: str
    is_primary: bool = Field(default=True, alias="isPrimary")
    first_name: Optional[str] = Field(default=None, alias="firstName")
    last_name: Optional[str] = Field(default=None, alias="lastName")
    date_of_birth: Optional[str] = Field(default=None, alias="dateOfBirth")

    class Config:
        populate_by_name = True


class Premium(BaseModel):
    annual_premium: Optional[float] = Field(default=None, alias="annualPremium")
    currency: str = "USD"
    payment_frequency: Optional[str] = Field(default=None, alias="paymentFrequency")

    class Config:
        populate_by_name = True


class Jurisdiction(BaseModel):
    state: Optional[str] = None
    country: Optional[str] = None


class Policy(BaseModel):
    # Business key. Renamed from `policyNumber` for consistency with `memberId`,
    # `planId`, `claimId` and `traceId`; `_id` is an ObjectId and is not a join
    # key anywhere in the model.
    policy_id: str = Field(alias="policyId")
    policy_type: Optional[str] = Field(default=None, alias="policyType")
    plan_id: str = Field(alias="planId")
    status: str
    version: int = 1
    is_latest_version: bool = Field(default=True, alias="isLatestVersion")
    effective_period: Optional[EffectivePeriod] = Field(default=None, alias="effectivePeriod")
    original_effective_date: Optional[str] = Field(default=None, alias="originalEffectiveDate")
    parties: List[Party] = []
    premium: Optional[Premium] = None
    agent_id: Optional[str] = Field(default=None, alias="agentId")
    agency_id: Optional[str] = Field(default=None, alias="agencyId")
    jurisdiction: Optional[Jurisdiction] = None
    claims: List[str] = []
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")

    class Config:
        populate_by_name = True
