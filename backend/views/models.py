"""Response models for composed reads."""

from pydantic import BaseModel, Field
from typing import Optional, List

from clinical.profiles.models import (
    ClinicalHistory,
    CurrentCarePlan,
    PendingAction,
)
from insurance.members.models import Eligibility


class Summary(BaseModel):
    """The member's rolling summary, merged from both sides: the authorization fields are
    the insurance side's, `active_condition_count` the clinical side's."""

    active_condition_count: int
    open_authorization_count: int
    last_authorization_status: str
    updated_at: str


class Member(BaseModel):
    """The combined member document, exactly as the frontend has always read it.

    Identity, policy link and eligibility come from the insurance database; history, care
    plan and pending actions from the clinical one. Demographics are duplicated on both
    sides on purpose, and the insurance copy is the one returned.
    """

    member_id: str = Field(alias="memberId")
    policy_id: str = Field(alias="policyId")
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    date_of_birth: Optional[str] = Field(default=None, alias="dateOfBirth")
    gender: Optional[str] = None
    state: Optional[str] = None
    preferred_language: Optional[str] = Field(default=None, alias="preferredLanguage")
    sin_encrypted: Optional[str] = None
    phi_encrypted: Optional[str] = None
    eligibility: Eligibility
    clinical_history: ClinicalHistory
    current_care_plan: CurrentCarePlan
    pending_actions: List[PendingAction] = Field(default=[], alias="pendingActions")
    summary: Summary
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")

    class Config:
        populate_by_name = True
