"""Models for the insurance side of a member.

A member in the insurance database is identity, `policyId`, `eligibility` and a two-field
summary. History, notes, care plan and physician orders live in the clinical database and
are joined onto the member only in `views/`.
"""

from pydantic import BaseModel, Field
from typing import Optional


class Eligibility(BaseModel):
    status: str
    effective_date: str = Field(alias="effectiveDate")
    tier: str
    term_date: Optional[str] = Field(default=None, alias="termDate")

    class Config:
        populate_by_name = True


class InsuranceSummary(BaseModel):
    """The two fields the insurance side owns. `active_condition_count` is a clinical
    figure and is added by the composed member view."""

    open_authorization_count: int
    last_authorization_status: str
    updated_at: Optional[str] = None


class InsuranceMember(BaseModel):
    member_id: str = Field(alias="memberId")
    policy_id: str = Field(alias="policyId")
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    date_of_birth: Optional[str] = Field(default=None, alias="dateOfBirth")
    gender: Optional[str] = None
    state: Optional[str] = None
    preferred_language: Optional[str] = Field(default=None, alias="preferredLanguage")
    sin_encrypted: Optional[str] = None
    eligibility: Eligibility
    summary: InsuranceSummary
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")

    class Config:
        populate_by_name = True
