"""Models for the clinical profile: history, care plan and the physician's order.

Field names and shapes are unchanged from the combined member document the frontend already
reads, so the composed member view (`views/`) can hand the UI the shape it expects.
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
    # Float: a gap-review entry records the `effective_trial_months` derived from fill
    # dates, which can be fractional.
    duration_months: float
    outcome: str
    notes: str
    documented_by: str
    documented_on: str
    related_note: Optional[str] = None


class ClinicalNote(BaseModel):
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


class ManagingProvider(BaseModel):
    """The treating clinician, embedded on the care plan."""
    provider_id: str = Field(alias="providerId")
    name: str
    specialty: Optional[str] = None

    class Config:
        populate_by_name = True


class CurrentCarePlan(BaseModel):
    considering_therapy: Optional[str] = None
    # Set by the backend's clinical sync when an authorization for the therapy closes as an
    # approval; `considering_therapy` is cleared at that point.
    approved_therapy: Optional[str] = None
    managing_provider: Optional[ManagingProvider] = None


class PendingAction(BaseModel):
    """The physician's order: the frontend's "Pending Actions" card, and what triggers the
    prior-authorization flow. `related_diagnosis_code` stays on this side only; the backend
    passes it to the Insurance Agent in the opening message."""

    action_id: str = Field(alias="actionId")
    type: str                       # e.g. DIAGNOSIS_FOLLOW_UP
    status: str                     # pending | in_progress | resolved
    related_diagnosis_code: Optional[str] = Field(default=None, alias="relatedDiagnosisCode")
    proposed_treatment: Optional[str] = Field(default=None, alias="proposedTreatment")
    raised_by: Optional[str] = Field(default=None, alias="raisedBy")
    raised_at: Optional[str] = Field(default=None, alias="raisedAt")
    linked_audit_trace_id: Optional[str] = Field(default=None, alias="linkedAuditTraceId")

    class Config:
        populate_by_name = True


class ClinicalSummary(BaseModel):
    """Clinical counts only. The authorization counts live on the insurance member."""

    active_condition_count: int = 0
    updated_at: Optional[str] = None


class ClinicalProfile(BaseModel):
    member_id: str = Field(alias="memberId")
    phi_encrypted: Optional[str] = None
    clinical_history: ClinicalHistory
    current_care_plan: CurrentCarePlan
    pending_actions: List[PendingAction] = Field(default=[], alias="pendingActions")
    summary: ClinicalSummary = ClinicalSummary()
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")

    class Config:
        populate_by_name = True
