"""Pydantic models for member domain."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class Diagnosis(BaseModel):
    code: str
    system: str
    display: str
    status: str


class Medication(BaseModel):
    code: str
    system: str
    display: str
    status: str
    reason: Optional[str] = None


class TreatmentResponse(BaseModel):
    drug: str
    duration_months: int
    outcome: str
    notes: str
    documented_by: str
    documented_on: str


class ClinicalHistory(BaseModel):
    diagnoses: List[Diagnosis]
    medications: List[Medication]
    treatment_responses: List[TreatmentResponse]


class Eligibility(BaseModel):
    status: str
    effective_date: str
    tier: str
    term_date: Optional[str] = None


class Demographics(BaseModel):
    name: str
    birth_date: str
    gender: str
    occupation: str


class CurrentCarePlan(BaseModel):
    # Not set until the inadequate first-line response is documented (Phase 1).
    considering_therapy: Optional[str] = None
    managing_provider: str


class Summary(BaseModel):
    active_condition_count: int
    open_authorization_count: int
    last_authorization_status: str
    updated_at: str


class MemberClinicalContext(BaseModel):
    member_id: str = Field(alias="_id")
    clinical_history: ClinicalHistory
    eligibility: Eligibility
    current_care_plan: Optional[CurrentCarePlan] = None

    class Config:
        populate_by_name = True


class Member(BaseModel):
    member_id: str = Field(alias="_id")
    plan_id: str
    eligibility: Eligibility
    demographics: Demographics
    clinical_history: ClinicalHistory
    current_care_plan: CurrentCarePlan
    summary: Summary
    updated_at: str

    class Config:
        populate_by_name = True


class MemberList(BaseModel):
    count: int
    members: List[Member]
