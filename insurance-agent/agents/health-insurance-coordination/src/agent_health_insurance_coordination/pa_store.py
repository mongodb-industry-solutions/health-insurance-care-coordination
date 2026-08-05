"""PriorAuthStore - MongoDB access layer for the prior-authorization data model.

Implements the object model documented in
`insurance-agent/sources/Prior_Authorization_Agent_Reference.md`:

    members    - the single, continuously-updated operational record
    policies   - the member's contract, referencing exactly one plan
    plans      - coverage rules with treatments[]/steps[] embedded
    claims     - financial record bridging a health event and its outcome
    audit_log  - regulator-ready decision traces, one per decision
    guidelines - clinical reference data (taxonomic + procedural memory)
    notifications - member-facing messages about a decision

Field names here mirror the seeded `health_insurance_agent` database exactly:
top-level business keys are camelCase (`memberId`, `policyNumber`, `planId`,
`treatmentCode`), while the clinical sub-documents the model inherited from the
source systems stay snake_case (`clinical_history`, `current_care_plan`,
`summary`, and the guideline documents). Do not "normalize" one into the other --
the queries below have to match what is on disk.

Deterministic decision logic (eligibility, coverage, step therapy, confidence
aggregation) lives in module-level functions rather than inside the tools, so
that the same rules are applied identically on every request and can be unit
tested without a database or an LLM.
"""

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field
from pymongo import ASCENDING, MongoClient

logger = logging.getLogger(__name__)

# Collection name constants — these match the seeded database and must not change.
MEMBERS_COLLECTION = "members"
POLICIES_COLLECTION = "policies"
PLANS_COLLECTION = "plans"
CLAIMS_COLLECTION = "claims"
AUDIT_LOG_COLLECTION = "audit_log"
GUIDELINES_COLLECTION = "guidelines"
NOTIFICATIONS_COLLECTION = "notifications"

# Reasoning-step memory types. `semantic` and `taxonomic` are reference-data
# lookups; `episodic` and `procedural` are the clinical judgement steps, and
# their presence on a denial is what makes that denial a *clinical* one.
MemoryType = Literal["semantic", "taxonomic", "episodic", "procedural"]
CLINICAL_MEMORY_TYPES = ("episodic", "procedural")

# Decision vocabulary shared by audit_log.outcome.decision and claims.status.
Decision = Literal["approved", "approved_restricted", "denied", "pending"]

# The only two grounds on which the agent may close a case by itself.
AdministrativeReason = Literal["benefit_exclusion", "eligibility_lapsed"]

# Confidence aggregation (see aggregate_confidence). Documented and fixed,
# because the bounded-authority gate keys off this number.
CLINICAL_FAILURE_PENALTY = 0.55


# =============================================================================
# Write models
# =============================================================================


class ClaimProvider(BaseModel):
    """Treating provider, embedded on the claim rather than modeled separately."""

    providerId: str
    name: str
    specialty: str


class NewClaim(BaseModel):
    """A claim opened for a requested or delivered service."""

    claimId: str
    memberId: str
    policyId: str
    provider: ClaimProvider
    procedureCode: str = Field(..., description="Matches plans.treatments[].treatmentCode")
    procedureDesc: str
    diagnosisCode: str = Field(..., description="Matches plans.treatments[].condition")
    diagnosisDisplay: str
    serviceDate: str
    claimType: str = Field(..., description="specialty_pharmacy / pharmacy / medical")
    billedAmt: float
    paidAmt: float = 0.0
    memberOwed: float = 0.0
    currency: str = "USD"
    status: str = "pending"
    denialReason: Optional[str] = None
    linkedAuditTraceId: Optional[str] = None


class ReasoningStep(BaseModel):
    """One memory-tagged step in a decision trace."""

    stepId: str
    memoryType: MemoryType
    name: str
    input: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    confidence: float
    detail: str = Field(..., description="Plain-language explanation, required for auditors")


# =============================================================================
# Deterministic decision logic (no database, no LLM)
# =============================================================================


def _as_date(value: Any) -> Optional[date]:
    """Parse the date shapes present in this database into a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def utc_now_iso() -> str:
    """Timestamp in the same shape as the seeded documents (…Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_iso() -> str:
    """Today's service date, in the `YYYY-MM-DD` shape the data model uses."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def new_trace_id() -> str:
    return f"TRC-{uuid.uuid4().hex[:10].upper()}"


def new_claim_id() -> str:
    return f"CLM-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:7].upper()}"


def new_notification_id() -> str:
    return f"NOTIF-{uuid.uuid4().hex[:10]}"


def evaluate_eligibility(policy: dict, service_date: str) -> dict:
    """First administrative gate: was coverage active on the service date?

    Evaluates `status` together with `effectivePeriod`, because a policy can be
    marked ACTIVE and still not cover a date outside its term (and vice versa).
    """
    requested = _as_date(service_date)
    if requested is None:
        return {"eligible": False, "reason": "invalid_service_date"}

    period = policy.get("effectivePeriod") or {}
    effective = _as_date(period.get("effectiveDate"))
    expiry = _as_date(period.get("expiryDate"))
    status = (policy.get("status") or "").upper()

    if effective and requested < effective:
        return {
            "eligible": False,
            "reason": "coverage_not_yet_effective",
            "detail": f"Service date {service_date} precedes effective date {effective.isoformat()}.",
        }
    if expiry and requested > expiry:
        return {
            "eligible": False,
            "reason": "eligibility_lapsed",
            "detail": (
                f"Policy term ended {expiry.isoformat()}; service requested {service_date} "
                "— not eligible on date of service."
            ),
        }
    if status != "ACTIVE":
        return {
            "eligible": False,
            "reason": "eligibility_lapsed",
            "detail": f"Policy status is {status or 'UNKNOWN'}, not ACTIVE.",
        }
    return {
        "eligible": True,
        "reason": None,
        "detail": f"Policy {policy.get('policyNumber')} active on {service_date}.",
    }


def check_treatment_coverage(
    plan: dict,
    treatment_code: str = "",
    condition: str = "",
    drug: str = "",
) -> dict:
    """Second administrative gate: does the plan cover this treatment, and which steps?

    Follows the coverage-check pseudocode in the reference document. A treatment
    is resolved by `treatmentCode` + `condition`, falling back to `drug` +
    `condition` so a therapy named in prose ("secukinumab") resolves without a
    code crosswalk.
    """
    code = (treatment_code or "").strip().upper()
    wanted_drug = (drug or "").strip().lower()
    wanted_condition = (condition or "").strip().upper()

    entry = None
    for candidate in plan.get("treatments") or []:
        cand_condition = (candidate.get("condition") or "").upper()
        if wanted_condition and cand_condition != wanted_condition:
            continue
        cand_code = (candidate.get("treatmentCode") or "").upper()
        cand_drug = (candidate.get("drug") or "").lower()
        if (code and cand_code == code) or (wanted_drug and cand_drug == wanted_drug):
            entry = candidate
            break

    if entry is None:
        return {
            "covered": False,
            "restriction": None,
            "coveredSteps": [],
            "uncoveredSteps": [],
            "priorAuthRequired": None,
            "reason": "treatment_not_listed_for_condition",
            "tier": None,
        }

    tier = entry.get("tier")
    if not entry.get("covered", False):
        return {
            "covered": False,
            "restriction": None,
            "coveredSteps": [],
            "uncoveredSteps": [s.get("stepCode") for s in entry.get("steps") or []],
            "priorAuthRequired": None,
            "reason": "benefit_exclusion",
            "tier": tier,
            "treatmentName": entry.get("treatmentName"),
        }

    steps = entry.get("steps") or []
    covered_steps = [s.get("stepCode") for s in steps if s.get("covered")]
    uncovered_steps = [s.get("stepCode") for s in steps if not s.get("covered")]

    if not covered_steps and steps:
        return {
            "covered": False,
            "restriction": None,
            "coveredSteps": [],
            "uncoveredSteps": uncovered_steps,
            "priorAuthRequired": entry.get("priorAuthRequired"),
            "reason": "no_steps_covered",
            "tier": tier,
            "treatmentName": entry.get("treatmentName"),
        }

    return {
        "covered": True,
        # "partial" is what makes an approved_restricted outcome data-driven
        # rather than narrative: some steps are funded and some are not.
        "restriction": "partial" if uncovered_steps else "none",
        "coveredSteps": covered_steps,
        "uncoveredSteps": uncovered_steps,
        "priorAuthRequired": entry.get("priorAuthRequired"),
        "reason": None,
        "tier": tier,
        "treatmentName": entry.get("treatmentName"),
    }


def evaluate_step_therapy(documented_months: float, required_months: float) -> dict:
    """Procedural gate: does the documented trial meet the encoded minimum?"""
    satisfied = documented_months >= required_months
    if satisfied:
        return {
            "satisfied": True,
            "confidence": 0.95,
            "detail": (
                f"Step therapy requires {required_months:g} months; "
                f"{documented_months:g} documented — satisfied."
            ),
        }
    return {
        "satisfied": False,
        "confidence": 0.90,
        "detail": (
            f"Step therapy requires {required_months:g} months; "
            f"{documented_months:g} documented — not satisfied."
        ),
    }


def aggregate_confidence(step_confidences: List[float], criteria_satisfied: bool = True) -> float:
    """Aggregate step confidences into the overall decision confidence.

    Deterministic and documented, because the bounded-authority gate keys off
    this number and an opaque aggregation would undermine the audit trail:

    * the overall confidence is the **minimum** of the step confidences — a
      chain of reasoning is only as strong as its weakest link; and
    * when a clinical criterion was evaluated and **not** satisfied, a fixed
      penalty of 0.55 is subtracted. High confidence that a criterion failed is
      not confidence in the resulting adverse decision, and this is what drives
      such a case below every guideline threshold and into human review.
    """
    if not step_confidences:
        return 0.0
    overall = min(step_confidences)
    if not criteria_satisfied:
        overall -= CLINICAL_FAILURE_PENALTY
    return round(max(overall, 0.0), 2)


def summarize_trial_history(member: dict, drug: str) -> dict:
    """Episodic memory, within-member: the member's own documented trial of a drug.

    Takes the longest documented duration for the drug (later entries supersede
    earlier interim ones rather than adding to them), and surfaces any anomaly
    — a documented medication hold, or a gap flagged by an earlier review — so
    that an apparent discontinuation is investigated rather than assumed.
    """
    wanted = (drug or "").strip().lower()
    history = (member.get("clinical_history") or {})
    responses = [
        r
        for r in history.get("treatment_responses") or []
        if (r.get("drug") or "").lower() == wanted
    ]
    durations = [float(r.get("duration_months") or 0) for r in responses]
    effective_months = max(durations) if durations else 0.0

    # An anomaly is either a note explaining an interruption, or a prior
    # `gap_reviewed` response entry documenting that one was investigated.
    notes = [
        n
        for n in history.get("clinical_notes") or []
        if (n.get("type") or "") in ("medication_hold", "refill_gap", "gap_review")
    ]
    gap_reviewed = [r for r in responses if (r.get("outcome") or "") == "gap_reviewed"]

    anomaly_detected = bool(notes or gap_reviewed)
    explanation = None
    if notes:
        explanation = notes[-1].get("note")
    elif gap_reviewed:
        explanation = gap_reviewed[-1].get("notes")

    return {
        "effectiveTrialMonths": effective_months,
        "anomalyDetected": anomaly_detected,
        # An anomaly counts as explained only when documentation explains it.
        # An unexplained gap must lower confidence, never be resolved silently
        # in the member's favour.
        "anomalyExplained": bool(anomaly_detected and explanation),
        "explanation": explanation,
        "responses": responses,
    }


# =============================================================================
# Store
# =============================================================================


class PriorAuthStore:
    """MongoDB-backed access to the prior-authorization collections."""

    def __init__(self, mongodb_uri: str, database: str):
        # 2 s fast-fail rather than the default 30 s hang when unreachable.
        self._client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=2000)
        self._db = self._client[database]
        self.members = self._db[MEMBERS_COLLECTION]
        self.policies = self._db[POLICIES_COLLECTION]
        self.plans = self._db[PLANS_COLLECTION]
        self.claims = self._db[CLAIMS_COLLECTION]
        self.audit_log = self._db[AUDIT_LOG_COLLECTION]
        self.guidelines = self._db[GUIDELINES_COLLECTION]
        self.notifications = self._db[NOTIFICATIONS_COLLECTION]

    def ensure_indexes(self) -> None:
        """Create the read paths the tools rely on.

        The database is seeded externally, so this only adds indexes and never
        writes or reshapes documents.
        """
        self.members.create_index("memberId", unique=True)
        self.members.create_index("policyId")
        self.policies.create_index("policyNumber", unique=True)
        self.policies.create_index("planId")
        self.plans.create_index("planId", unique=True)
        self.claims.create_index("claimId", unique=True)
        self.claims.create_index([("memberId", ASCENDING), ("serviceDate", ASCENDING)])
        self.claims.create_index("linkedAuditTraceId")
        self.audit_log.create_index("traceId", unique=True)
        self.audit_log.create_index([("subjectRef", ASCENDING), ("createdAt", ASCENDING)])
        self.audit_log.create_index("contextSnapshot.guidelineRef")
        self.guidelines.create_index("condition")
        self.notifications.create_index("member_id")

    # -- Member -------------------------------------------------------------

    def get_member(self, member_id: str) -> Optional[dict]:
        return self.members.find_one({"memberId": member_id.upper()}, {"_id": 0})

    def update_member_summary(
        self,
        member_id: str,
        last_authorization_status: str,
        open_authorization_delta: int,
    ) -> Optional[dict]:
        """Refresh the rolling `summary` projection after a decision closes."""
        member = self.get_member(member_id)
        if not member:
            return None
        summary = dict(member.get("summary") or {})
        diagnoses = ((member.get("clinical_history") or {}).get("diagnoses")) or []
        open_count = int(summary.get("open_authorization_count") or 0) + open_authorization_delta
        summary.update(
            {
                "active_condition_count": len(
                    [d for d in diagnoses if (d.get("status") or "active") == "active"]
                ),
                "open_authorization_count": max(open_count, 0),
                "last_authorization_status": last_authorization_status,
                "updated_at": utc_now_iso(),
            }
        )
        self.members.update_one(
            {"memberId": member_id.upper()},
            {"$set": {"summary": summary, "updatedAt": utc_now_iso()}},
        )
        return summary

    # -- Policy & Plan ------------------------------------------------------

    def get_policy(self, policy_id: str) -> Optional[dict]:
        return self.policies.find_one({"policyNumber": policy_id.upper()}, {"_id": 0})

    def get_policy_by_member(self, member_id: str) -> Optional[dict]:
        member = self.get_member(member_id)
        if not member or not member.get("policyId"):
            return None
        return self.get_policy(member["policyId"])

    def get_plan(self, plan_id: str) -> Optional[dict]:
        return self.plans.find_one({"planId": plan_id.upper()}, {"_id": 0})

    # -- Clinical guidelines ------------------------------------------------

    def get_guideline(self, guideline_id: str) -> Optional[dict]:
        return self.guidelines.find_one({"_id": guideline_id})

    def get_guideline_for_condition(self, condition: str) -> Optional[dict]:
        """Newest effective guideline for a condition (criteria are versioned)."""
        return self.guidelines.find_one(
            {"condition": condition.upper()},
            sort=[("effective_date", -1)],
        )

    def find_guidelines_classifying(self, drug: str) -> List[dict]:
        """Guidelines whose `classification` enumerates this drug."""
        return list(self.guidelines.find({f"classification.{drug.lower()}": {"$exists": True}}))

    # -- Claims -------------------------------------------------------------

    def get_claim(self, claim_id: str) -> Optional[dict]:
        return self.claims.find_one({"claimId": claim_id.upper()}, {"_id": 0})

    def list_claims_by_member(self, member_id: str) -> List[dict]:
        return list(
            self.claims.find({"memberId": member_id.upper()}, {"_id": 0}).sort("serviceDate", 1)
        )

    def create_claim(self, claim: NewClaim) -> dict:
        doc = claim.model_dump()
        doc["_id"] = doc["claimId"]
        doc["createdAt"] = utc_now_iso()
        doc["updatedAt"] = doc["createdAt"]
        self.claims.insert_one(doc)
        # Keep the policy's claims[] back-reference current.
        self.policies.update_one(
            {"policyNumber": doc["policyId"].upper()},
            {"$addToSet": {"claims": doc["claimId"]}, "$set": {"updatedAt": doc["updatedAt"]}},
        )
        return {k: v for k, v in doc.items() if k != "_id"}

    def update_claim(self, claim_id: str, updates: dict) -> Optional[dict]:
        updates = dict(updates)
        updates["updatedAt"] = utc_now_iso()
        result = self.claims.find_one_and_update(
            {"claimId": claim_id.upper()},
            {"$set": updates},
            return_document=True,
        )
        if not result:
            return None
        return {k: v for k, v in result.items() if k != "_id"}

    def list_drug_fills(self, member_id: str, rxnorm: str) -> List[dict]:
        """Pharmacy fills for one drug, in service-date order.

        Fill history is how a refill gap becomes visible: the fills carry
        `presentation_profile.fill_number`, so a missing number is a gap.
        """
        return list(
            self.claims.find(
                {"memberId": member_id.upper(), "procedureCode": rxnorm},
                {"_id": 0, "claimId": 1, "serviceDate": 1, "presentation_profile": 1},
            ).sort("serviceDate", 1)
        )

    # -- Audit log ----------------------------------------------------------

    def create_trace(
        self,
        decision_type: str,
        subject_ref: str,
        subject_type: str,
        triggered_by: str,
        guideline_ref: Optional[str] = None,
        input_facts: Optional[List[str]] = None,
        retention_years: int = 7,
    ) -> dict:
        now = utc_now_iso()
        trace_id = new_trace_id()
        doc = {
            "_id": trace_id,
            "traceId": trace_id,
            "decisionType": decision_type,
            "subjectRef": subject_ref.upper(),
            "subjectType": subject_type.upper(),
            "audit": {
                "triggeredBy": triggered_by,
                "triggeredAt": now,
                "reviewRequired": False,
                "reviewRequiredReason": None,
                "regulatoryFlags": ["CMS-PA-RULE"],
                "retentionYears": retention_years,
            },
            "contextSnapshot": {
                "guidelineRef": guideline_ref,
                "inputFacts": list(input_facts or []),
            },
            "steps": [],
            "outcome": None,
            "review": {
                "routedToHuman": False,
                "finalDecisionMaker": None,
                "closedBy": None,
                "closedAt": None,
            },
            "linkedTraces": [],
            "createdAt": now,
            "updatedAt": now,
        }
        self.audit_log.insert_one(doc)
        return {k: v for k, v in doc.items() if k != "_id"}

    def get_trace(self, trace_id: str) -> Optional[dict]:
        return self.audit_log.find_one({"traceId": trace_id.upper()}, {"_id": 0})

    def list_traces(self, subject_ref: str) -> List[dict]:
        return list(
            self.audit_log.find({"subjectRef": subject_ref.upper()}, {"_id": 0}).sort(
                "createdAt", 1
            )
        )

    def list_traces_by_claim(self, claim_id: str) -> List[dict]:
        claim = self.get_claim(claim_id)
        if not claim:
            return []
        trace_ids = [t for t in [claim.get("linkedAuditTraceId")] if t]
        return list(
            self.audit_log.find(
                {"$or": [{"traceId": {"$in": trace_ids}}, {"subjectRef": claim_id.upper()}]},
                {"_id": 0},
            ).sort("createdAt", 1)
        )

    def append_step(self, trace_id: str, step: ReasoningStep) -> Optional[dict]:
        result = self.audit_log.find_one_and_update(
            {"traceId": trace_id.upper()},
            {
                "$push": {"steps": step.model_dump()},
                "$set": {"updatedAt": utc_now_iso()},
            },
            return_document=True,
            projection={"_id": 0, "steps": 1, "traceId": 1},
        )
        return result

    def add_input_facts(self, trace_id: str, facts: List[str]) -> None:
        if not facts:
            return
        self.audit_log.update_one(
            {"traceId": trace_id.upper()},
            {
                "$push": {"contextSnapshot.inputFacts": {"$each": facts}},
                "$set": {"updatedAt": utc_now_iso()},
            },
        )

    def set_outcome(
        self,
        trace_id: str,
        decision: str,
        rationale: str,
        confidence: float,
    ) -> Optional[dict]:
        """Record a recommendation. Never touches `review.closedBy`."""
        return self.audit_log.find_one_and_update(
            {"traceId": trace_id.upper()},
            {
                "$set": {
                    "outcome": {
                        "decision": decision,
                        "rationale": rationale,
                        "confidence": confidence,
                        "overrideFlag": False,
                        "overrideBy": None,
                        "overrideReason": None,
                    },
                    "status": decision,
                    "updatedAt": utc_now_iso(),
                }
            },
            return_document=True,
            projection={"_id": 0},
        )

    def set_escalation(
        self,
        trace_id: str,
        reason: str,
        final_decision_maker: str,
    ) -> Optional[dict]:
        return self.audit_log.find_one_and_update(
            {"traceId": trace_id.upper()},
            {
                "$set": {
                    "audit.reviewRequired": True,
                    "audit.reviewRequiredReason": reason,
                    "review.routedToHuman": True,
                    "review.finalDecisionMaker": final_decision_maker,
                    "status": "pending_review",
                    "updatedAt": utc_now_iso(),
                },
                "$addToSet": {"audit.regulatoryFlags": reason},
            },
            return_document=True,
            projection={"_id": 0, "audit": 1, "review": 1, "traceId": 1},
        )

    def close_trace(
        self,
        trace_id: str,
        closed_by: str,
        final_decision_maker: str,
        regulatory_flag: Optional[str] = None,
        override: Optional[dict] = None,
    ) -> Optional[dict]:
        now = utc_now_iso()
        updates: dict[str, Any] = {
            "review.closedBy": closed_by,
            "review.closedAt": now,
            "review.finalDecisionMaker": final_decision_maker,
            "updatedAt": now,
        }
        if override:
            updates["outcome.overrideFlag"] = bool(override.get("overrideFlag"))
            updates["outcome.overrideBy"] = override.get("overrideBy")
            updates["outcome.overrideReason"] = override.get("overrideReason")
            if override.get("decision"):
                updates["outcome.decision"] = override["decision"]
                updates["status"] = override["decision"]
        update: dict[str, Any] = {"$set": updates}
        if regulatory_flag:
            update["$addToSet"] = {"audit.regulatoryFlags": regulatory_flag}
        return self.audit_log.find_one_and_update(
            {"traceId": trace_id.upper()},
            update,
            return_document=True,
            projection={"_id": 0},
        )

    def find_comparable_cases(
        self,
        condition: str,
        drug_class: str = "",
        prior_therapy_months: float = 0.0,
    ) -> dict:
        """Episodic memory across members, as aggregate counts and IDs only.

        Deliberately returns no other member's PHI: identifiers, counts, and the
        de-identified presentation profile that makes a precedent comparable.
        """
        condition = condition.upper()

        precedents = list(
            self.claims.find(
                {
                    "diagnosisCode": condition,
                    "claimType": "specialty_pharmacy",
                    "presentation_profile.trial_months": {"$exists": True},
                },
                {
                    "_id": 0,
                    "claimId": 1,
                    "procedureCode": 1,
                    "outcome": 1,
                    "status": 1,
                    "presentation_profile": 1,
                },
            )
        )

        traces = list(
            self.audit_log.find(
                {
                    "decisionType": "PRIOR_AUTHORIZATION",
                    "outcome.decision": {"$exists": True},
                    "contextSnapshot.guidelineRef": {"$exists": True},
                },
                {"_id": 0, "traceId": 1, "outcome.decision": 1, "contextSnapshot.guidelineRef": 1},
            )
        )
        guideline = self.get_guideline_for_condition(condition)
        guideline_ref = guideline.get("_id") if guideline else None
        traces = [
            t
            for t in traces
            if not guideline_ref
            or (t.get("contextSnapshot") or {}).get("guidelineRef") == guideline_ref
        ]

        approved = [
            p for p in precedents if (p.get("outcome") or p.get("status")) in ("approved", "paid")
        ]
        denied = [p for p in precedents if (p.get("outcome") or p.get("status")) == "denied"]
        approved += [t for t in traces if (t.get("outcome") or {}).get("decision") == "approved"]
        denied += [t for t in traces if (t.get("outcome") or {}).get("decision") == "denied"]

        return {
            "condition": condition,
            "drugClass": drug_class,
            "priorTherapyMonths": prior_therapy_months,
            "comparableTraceIds": [t["traceId"] for t in traces],
            "comparableClaimIds": [p["claimId"] for p in precedents],
            "approvedCount": len(approved),
            "deniedCount": len(denied),
            "profiles": [
                {
                    "claimId": p["claimId"],
                    "treatmentCode": p.get("procedureCode"),
                    "outcome": p.get("outcome") or p.get("status"),
                    "priorTherapy": (p.get("presentation_profile") or {}).get("prior_therapy"),
                    "trialMonths": (p.get("presentation_profile") or {}).get("trial_months"),
                    "trialOutcome": (p.get("presentation_profile") or {}).get("trial_outcome"),
                }
                for p in precedents
            ],
        }

    # -- Notifications ------------------------------------------------------

    def create_notification(
        self,
        member_id: str,
        message: str,
        status: str,
        trace_id: Optional[str] = None,
    ) -> dict:
        doc = {
            "_id": new_notification_id(),
            "member_id": member_id.upper(),
            "trace_id": trace_id,
            "status": status,
            "message": message,
            "created_at": utc_now_iso(),
            "read": False,
        }
        self.notifications.insert_one(doc)
        return {"notification_id": doc["_id"], **{k: v for k, v in doc.items() if k != "_id"}}


def create_prior_auth_store(mongodb_uri: str, database: str) -> Optional[PriorAuthStore]:
    """Factory: returns None when MongoDB is not configured, so tools can say so."""
    if not mongodb_uri:
        logger.warning("MONGODB_URI is not set — prior-authorization data tools are unavailable.")
        return None
    try:
        store = PriorAuthStore(mongodb_uri, database)
        store.ensure_indexes()
        return store
    except Exception as e:
        logger.warning(f"Failed to create PriorAuthStore: {e}")
        return None
