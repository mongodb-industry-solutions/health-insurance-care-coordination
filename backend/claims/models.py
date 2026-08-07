"""Pydantic models for claims domain.

The Claim is the financial record connecting a health event to its insurance
outcome — one of the two central objects (with Member). The treating provider is
embedded directly. A claim carries a linked Audit Log trace (`linked_audit_trace_id`)
only when the underlying service required prior authorization.

Financial fields (billed/paid/owed) are modeled for realism per the official data
model, but the demo performs NO adjudication math — they are seeded static values.

`service`/`diagnosis`/`presentation_profile` are retained alongside the richer
coded fields because comparable-case (episodic) retrieval keys off them.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ClaimProvider(BaseModel):
    provider_id: str = Field(alias="providerId")
    name: Optional[str] = None
    specialty: Optional[str] = None

    class Config:
        populate_by_name = True


class Claim(BaseModel):
    claim_id: str = Field(alias="claimId")
    member_id: str = Field(alias="memberId")
    policy_id: Optional[str] = Field(default=None, alias="policyId")
    provider: Optional[ClaimProvider] = None

    # Coded clinical detail
    procedure_code: Optional[str] = Field(default=None, alias="procedureCode")
    procedure_desc: Optional[str] = Field(default=None, alias="procedureDesc")
    diagnosis_code: Optional[str] = Field(default=None, alias="diagnosisCode")
    diagnosis_display: Optional[str] = Field(default=None, alias="diagnosisDisplay")

    # Legacy retrieval keys. The final data model dropped them in favour of the
    # coded fields above (`procedureDesc`, `diagnosisCode`, `status`), so live
    # documents do not carry them and all three are optional. Comparable-case
    # retrieval now matches on the coded fields and maps them back onto this shape
    # — see `ClaimRepository.find_comparable`.
    service: Optional[str] = None
    diagnosis: Optional[str] = None
    outcome: Optional[str] = None
    presentation_profile: Optional[Dict[str, Any]] = None

    service_date: Optional[str] = Field(default=None, alias="serviceDate")
    claim_type: Optional[str] = Field(default=None, alias="claimType")

    # Financials — modeled, not computed (no adjudication math in the demo)
    billed_amt: Optional[float] = Field(default=None, alias="billedAmt")
    paid_amt: Optional[float] = Field(default=None, alias="paidAmt")
    member_owed: Optional[float] = Field(default=None, alias="memberOwed")
    currency: Optional[str] = None

    status: Optional[str] = None
    denial_reason: Optional[str] = Field(default=None, alias="denialReason")
    # Reference to the Audit Log trace that authorized this claim, if prior auth applied.
    linked_audit_trace_id: Optional[str] = Field(default=None, alias="linkedAuditTraceId")

    adjudicated_at: Optional[str] = None
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")

    class Config:
        populate_by_name = True


class ComparableClaim(BaseModel):
    """Projected shape returned by comparable-case retrieval (episodic memory).

    Only the fields the agent needs to judge similarity — service, outcome, and
    the presentation_profile — plus ids to cite the precedent.

    `service` and `outcome` are the shape the agent's prompts already read. The
    repository maps them from the coded fields the final data model actually
    carries (`procedureDesc` and `status`), so this response shape is stable even
    though its source fields changed.
    """
    claim_id: str = Field(alias="claimId")
    member_id: Optional[str] = Field(default=None, alias="memberId")
    service: Optional[str] = None
    outcome: Optional[str] = None
    presentation_profile: Optional[Dict[str, Any]] = None

    class Config:
        populate_by_name = True


class RefillGap(BaseModel):
    """A break in a medication's refill cadence, found in the pharmacy claims."""
    drug: str
    previous_fill: str
    next_fill: str
    gap_days: int
    approx_missed_fills: int


class RefillGapsResponse(BaseModel):
    member_id: str
    drug: Optional[str] = None
    expected_cadence_days: int
    count: int
    gaps: List[RefillGap]


class ComparableClaimsQuery(BaseModel):
    service: str
    diagnosis: str


class ComparableClaimsResponse(BaseModel):
    query: ComparableClaimsQuery
    count: int
    claims: List[ComparableClaim]


class MemberClaimsResponse(BaseModel):
    member_id: str
    claim_count: int
    claims: List[Claim]


class ClaimsList(BaseModel):
    count: int
    claims: List[Claim]
