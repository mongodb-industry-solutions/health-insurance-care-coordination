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


class OpenCaseResponse(BaseModel):
    """The member's open pending action — how an agent handed only a `memberId`
    discovers what was requested and which trace to write reasoning to.

    Every case-specific field is optional because `has_open_case: false` is a
    legitimate answer, not an error.
    """
    member_id: str
    has_open_case: bool
    open_action_count: int
    action_id: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    proposed_treatment: Optional[str] = None
    # The referring physician's assertion of the drug/diagnosis pairing. Returned
    # for comparison only — `concept-match` derives the code independently and
    # must not be handed this value, or the verification becomes circular.
    related_diagnosis_code: Optional[str] = None
    raised_by: Optional[str] = None
    raised_at: Optional[str] = None
    # Null until the case is actually opened and a trace exists.
    trace_id: Optional[str] = None
    detail: str


class TrialGap(BaseModel):
    """One interruption in a drug's fill cadence."""
    drug: str
    previous_fill: str
    next_fill: str
    gap_days: int
    approx_missed_fills: int


class TrialHistoryResponse(BaseModel):
    """Step 5 (episodic memory): the member's trial of the required prior therapy,
    with the duration derived from pharmacy fills rather than taken on trust.

    `effective_trial_months` is the number Step 6 evaluates. It is the full observed
    span when the trial was continuous or an interruption was explained, and only the
    longest uninterrupted run when an interruption was not.
    """
    member_id: str
    drug: str
    # What the record claims, kept alongside the derived figure so a divergence
    # between the two is visible rather than silently overwritten.
    documented_months: float
    fill_count: int
    first_fill: Optional[str] = None
    last_fill: Optional[str] = None
    expected_cadence_days: int
    observed_span_months: Optional[int] = None
    longest_continuous_months: Optional[int] = None
    anomaly_detected: bool
    gaps: List[TrialGap] = []
    anomaly_explained: bool
    explanation: Optional[str] = None
    # The note_id that explained the gap, for provenance on the trace.
    related_note: Optional[str] = None
    effective_trial_months: float
    confidence: float
    detail: str


class ConceptMatchResponse(BaseModel):
    """Step 3 (semantic memory): the requested therapy resolved against the
    member's coded diagnoses, via whichever guideline classifies the drug."""
    member_id: str
    requested_treatment: str
    # The bare therapy name the match was performed on, after stripping any
    # "biologic therapy - " prefix.
    therapy: str
    matched: bool
    matched_condition: Optional[str] = None
    matched_display: Optional[str] = None
    # The guideline that supplied the drug-to-condition mapping — carried so the
    # caller can stamp `contextSnapshot.guidelineRef` without a second lookup.
    guideline_ref: Optional[str] = None
    # Both sides of the intersection, so a miss is explainable rather than opaque.
    member_diagnosis_codes: List[str] = []
    guideline_conditions: List[str] = []
    confidence: float
    detail: str

    
class PendingAuthorizationMember(BaseModel):
    """One row of the Insurance Agent's work queue.

    Deliberately narrower than `Member`: a queue view needs identity, the rolling
    summary and the open actions, not clinical history or encrypted PHI.
    """
    member_id: str = Field(alias="memberId")
    first_name: Optional[str] = Field(default=None, alias="firstName")
    last_name: Optional[str] = Field(default=None, alias="lastName")
    policy_id: Optional[str] = Field(default=None, alias="policyId")
    pending_actions: List[PendingAction] = Field(default=[], alias="pendingActions")
    summary: Optional[Summary] = None

    class Config:
        populate_by_name = True


class PendingAuthorizationsResponse(BaseModel):
    count: int
    members: List[PendingAuthorizationMember]


class PendingActionUpdateResponse(BaseModel):
    member_id: str = Field(alias="memberId")
    pending_action: PendingAction = Field(alias="pendingAction")
    updated_at: str = Field(alias="updatedAt")

    class Config:
        populate_by_name = True


class MemberSummaryResponse(BaseModel):
    member_id: str = Field(alias="memberId")
    summary: Summary
    # How many traces the counts were derived from — makes a surprising
    # open_authorization_count traceable to the data rather than to arithmetic.
    trace_count: int = Field(alias="traceCount")

    class Config:
        populate_by_name = True
