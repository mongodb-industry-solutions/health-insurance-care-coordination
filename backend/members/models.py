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
    # Provenance for a gap-review conclusion: the note_id of the clinical note that
    # explained the refill gap (verification agent, Phase 2). Optional — ordinary
    # treatment responses don't cite a note.
    related_note: Optional[str] = None


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
    effective_date: str = Field(alias="effectiveDate")
    tier: str
    term_date: Optional[str] = Field(default=None, alias="termDate")

    class Config:
        populate_by_name = True


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


class PendingAction(BaseModel):
    """An open item on the member's record — the frontend's "Pending Actions" card.

    A `DIAGNOSIS_FOLLOW_UP` action is what triggers the prior-authorization flow:
    it closes the gap between "a doctor recommended something" (already in
    `clinical_history`) and "the platform has a live, actionable trigger for it."
    The insurance agent reads `related_diagnosis_code`, `proposed_treatment` and
    `raised_by` off it to open the case, flips `status` to `in_progress` with
    `linked_audit_trace_id` attached, and marks it `resolved` at closure. An
    escalated case stays `in_progress`, so the frontend can distinguish "awaiting
    medical director" from "not started".

    Everything but the identity/status triple is optional: a freshly-raised action
    and a resolved one carry different subsets, and a strict model would fail
    validation on that variance rather than on anything actually wrong.
    """
    action_id: str = Field(alias="actionId")
    type: str                       # e.g. DIAGNOSIS_FOLLOW_UP
    status: str                     # pending | in_progress | resolved
    related_diagnosis_code: Optional[str] = Field(default=None, alias="relatedDiagnosisCode")
    proposed_treatment: Optional[str] = Field(default=None, alias="proposedTreatment")
    # The clinician who raised the item — this IS the referring physician; the
    # model has no separate field for one.
    raised_by: Optional[str] = Field(default=None, alias="raisedBy")
    raised_at: Optional[str] = Field(default=None, alias="raisedAt")
    # Null while still `pending`; populated once a trace exists.
    linked_audit_trace_id: Optional[str] = Field(default=None, alias="linkedAuditTraceId")

    class Config:
        populate_by_name = True


class Summary(BaseModel):
    active_condition_count: int
    open_authorization_count: int
    last_authorization_status: str
    updated_at: str


class MemberClinicalContext(BaseModel):
    member_id: str = Field(alias="memberId")
    clinical_history: ClinicalHistory
    eligibility: Eligibility
    current_care_plan: Optional[CurrentCarePlan] = None

    class Config:
        populate_by_name = True


class Member(BaseModel):
    # Business key. `_id` is a MongoDB-assigned ObjectId and is not a join key
    # anywhere in the model.
    member_id: str = Field(alias="memberId")
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
    # Open items on the record. Defaults to empty so a member with none still
    # validates.
    pending_actions: List[PendingAction] = Field(default=[], alias="pendingActions")
    summary: Summary
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")

    class Config:
        populate_by_name = True


class MemberList(BaseModel):
    count: int
    members: List[Member]
