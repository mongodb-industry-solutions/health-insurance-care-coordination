"""Pydantic models for member domain.

The Member is the core operational record: eligibility, demographics, and
clinical history (including the member's own treatment-response history, which
functions as episodic memory). Every authorization or claim decision reads this
record as-is; nothing about it is reconstructed at request time.

Schema follows the official data model: the member references a Policy
(`policy_id`), name is split into `first_name`/`last_name`, and sensitive
identifiers/PHI are carried as encrypted blobs (`sin_encrypted`, `phi_encrypted`).
"""

from pydantic import BaseModel, Field
from typing import Optional, List


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


class ClinicalNote(BaseModel):
    """A narrative clinical note from a visit or event — the source documentation
    supporting the coded record. Content lives here on the member (the continuous
    clinical context an agent reads)."""
    note_id: str
    date: str
    author: str
    type: str
    note: str


class ClinicalHistory(BaseModel):
    diagnoses: List[Diagnosis]
    medications: List[Medication]
    treatment_responses: List[TreatmentResponse]
    clinical_notes: List[ClinicalNote] = []


class Eligibility(BaseModel):
    status: str
    effective_date: str
    tier: str
    term_date: Optional[str] = None


class ManagingProvider(BaseModel):
    """The treating clinician, embedded on the care plan."""
    provider_id: str = Field(alias="providerId")
    name: str
    specialty: Optional[str] = None

    class Config:
        populate_by_name = True


class CurrentCarePlan(BaseModel):
    # Not set until the inadequate first-line response is documented (Phase 1).
    considering_therapy: Optional[str] = None
    # Set when an authorization for the therapy is finally approved (Phase 3);
    # considering_therapy is cleared at that point.
    approved_therapy: Optional[str] = None
    managing_provider: Optional[ManagingProvider] = None


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
    policy_id: str = Field(alias="policyId")
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    date_of_birth: Optional[str] = Field(default=None, alias="dateOfBirth")
    gender: Optional[str] = None
    state: Optional[str] = None
    preferred_language: Optional[str] = Field(default=None, alias="preferredLanguage")
    # Encrypted at rest — surfaced as opaque, base64-ish strings over the API, never
    # decrypted here. Optional so non-sensitive reads/tests need not supply them.
    sin_encrypted: Optional[str] = None
    phi_encrypted: Optional[str] = None
    eligibility: Eligibility
    clinical_history: ClinicalHistory
    current_care_plan: CurrentCarePlan
    summary: Summary
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")

    class Config:
        populate_by_name = True


class MemberList(BaseModel):
    count: int
    members: List[Member]
