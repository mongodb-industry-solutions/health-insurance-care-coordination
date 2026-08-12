"""Business logic for prior-authorization decision traces (the Audit Log).

A prior authorization is a decision-trace document in the `audit_log` collection.
This service owns its lifecycle — file -> process -> (auto-close | route to a
human) -> close — and, at process time, records the reasoning as a memory-typed
`steps[]` array (semantic / taxonomic / episodic / procedural) alongside a
regulator-ready `outcome` and `review` block.

Bounded authority is unchanged: an approval auto-closes only when the computed
confidence meets the guideline threshold; clinical denials and low-confidence
approvals route to a medical director. Agents never issue a final denial.
"""

import json
import random
import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from db.mdb import get_connector
from shared.summary import compute_summary_fields
from .repository import AuditRepository
from members.repository import MemberRepository
from policies.repository import PolicyRepository
from plans.repository import PlanRepository
from plans.service import PlanService
from guidelines.repository import GuidelineRepository
from claims.service import ClaimService


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# The four memory types a reasoning step may declare. Mandatory on every step:
# it is what makes "four memory types reasoning over one record" a queryable fact
# rather than an assertion about the model's internals.
MEMORY_TYPES = ("semantic", "taxonomic", "episodic", "procedural")

# The two that mark a determination as *clinical*. Their presence on a trace is
# what moves closure authority from the agent to a medical director, so this tuple
# is effectively the definition of a clinical decision in this system.
CLINICAL_MEMORY_TYPES = ("episodic", "procedural")

# Grounds on which the agent may close a case itself without human review. Both
# are factual gates that fire before clinical reasoning runs.
ADMIN_CLOSABLE_REASONS = ("eligibility_lapsed", "benefit_exclusion")

# The determination each administrative ground represents. An administrative
# closure records its own outcome from this map rather than requiring one to be on
# the trace already: for a factual gate the reason IS the decision, and nothing in
# the Insurance Agent's toolset writes `outcome` — that is step 7, which belongs to
# the clinical agent and never runs when the process short-circuits at step 1 or 2.
# Without this, every administrative denial was unclosable.
ADMIN_RATIONALES = {
    "eligibility_lapsed": (
        "Coverage was not active on the date of service. Administrative eligibility "
        "denial — the policy term decided the case, so no clinical review was required."
    ),
    "benefit_exclusion": (
        "The plan does not cover the requested treatment. Administrative "
        "benefit-exclusion denial — the benefit design decided the case, so no "
        "clinical review was required."
    ),
}

# An administrative determination is a factual comparison against records already
# on file, not a judgement. 1.0 is reserved for nothing, since the record itself
# could be wrong.
ADMIN_CONFIDENCE = 0.99

# Used when no guideline can be resolved. Deliberately strict: defaulting low
# would let a low-confidence approval close itself on missing reference data.
DEFAULT_CONFIDENCE_THRESHOLD = 0.90

ESCALATION_CLINICAL_DENIAL = "clinical_denial_requires_physician_closure"
ESCALATION_LOW_CONFIDENCE = "confidence_below_guideline_threshold"

APPROVAL_DECISIONS = ("approved", "approved_restricted")

# Outcomes a recommendation may propose. `pending` is included because "we could
# not settle this" is a legitimate recommendation — one that routes to a human —
# and forcing a reasoner to pick a direction it does not hold would be worse.
RECOMMENDABLE_DECISIONS = ("approved", "approved_restricted", "denied", "pending")

_ID_ATTEMPTS = 8


def _as_object(raw) -> dict:
    """Coerce a step's input/output argument into an object.

    Accepts JSON, and falls back to wrapping prose as `{"summary": ...}` rather
    than rejecting it — a reasoning step's evidence is worth recording even when
    the caller phrased it as a sentence.
    """
    if raw in (None, ""):
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"summary": str(raw)}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


class AuditService:
    """Service layer for prior-authorization decision traces."""

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self._connector = connector
        self.repository = AuditRepository(connector)
        self.member_repo = MemberRepository(connector)
        self.policy_repo = PolicyRepository(connector)
        self.plan_repo = PlanRepository(connector)
        self.guideline_repo = GuidelineRepository(connector)
        self.claim_service = ClaimService(connector)

    @staticmethod
    def _resolve_therapy(trace: dict, member: dict) -> str:
        """Name the therapy a trace approved, for the member's care plan.

        Three sources, most to least authoritative. `requested_service` is what the
        field is nominally for, but nothing currently writes it — the Insurance
        Agent's step 0 does not pass it — so in practice the pending action is what
        answers. Reading it by `linkedAuditTraceId` keeps the right answer when a
        member has more than one action.

        Returns "" when no source names a therapy, so callers can decline to write
        rather than blanking a care plan with an empty string.
        """
        requested = (trace.get("requested_service") or "").strip()
        if requested:
            return requested.replace("biologic therapy - ", "")

        trace_id = trace.get("traceId")
        for action in member.get("pendingActions") or []:
            if action.get("linkedAuditTraceId") == trace_id:
                proposed = (action.get("proposedTreatment") or "").strip()
                if proposed:
                    return proposed

        return ((member.get("current_care_plan") or {}).get("considering_therapy") or "").strip()

    def _mark_approved_therapy(self, member: dict, therapy: str) -> None:
        cp = member.setdefault("current_care_plan", {})
        cp["approved_therapy"] = therapy
        cp["considering_therapy"] = None

    def _recompute_summary(self, member: dict) -> None:
        """Recompute the member's small cross-domain summary from their traces.

        Derivation is delegated to `shared.summary`, which the Insurance Agent's
        `POST /api/members/{id}/summary` also uses — these fields are denormalized
        and have two writers, so a single shared derivation is what keeps the two
        from drifting.

        The previous implementation counted `t["status"]`, a top-level field the
        final data model does not define: it existed only on traces this service
        wrote itself, so a member whose traces came from anywhere else counted zero
        open authorizations and raised KeyError on `traces[-1]["status"]`. The
        shared version reads `outcome.decision` and `review.*` instead, and treats
        an unclosed trace as open — which is what makes an escalated case still
        count as outstanding.

        Still a whole-document upsert rather than a field-level `$set`, because
        callers mutate `member` in memory first (see `_mark_approved_therapy`) and
        rely on this call to persist those edits too.
        """
        traces = self.repository.find_by_member(member["memberId"])
        now = _now()
        summary = member.setdefault("summary", {})
        summary.update(compute_summary_fields(traces))
        summary["updated_at"] = now
        member["updatedAt"] = now
        self.member_repo.upsert(member)

    # =========================================================================
    # Insurance Agent: trace lifecycle (steps 0, 1-2, 8-9)
    # =========================================================================

    def list_all_traces(self) -> list:
        """Every decision trace in the system, newest first (compliance view)."""
        return self.repository.find_all_sorted()

    def _mint_trace_id(self, year: str) -> str:
        """Generate an unused `traceId` shaped like the existing data.

        `TRC-{YEAR}-PA-{5 digits}` — e.g. `TRC-2026-PA-44109` — matching the seeded
        traces, so the collection does not end up with two visibly different id
        styles.

        Randomly drawn, for the same reason as `claimId`: a max-scan-and-increment
        is racy between concurrent creates. Uniqueness rests on the unique index on
        `traceId`; this loop avoids provoking it, and the caller catches
        `DuplicateKeyError` for the race it cannot close.
        """
        prefix = f"TRC-{year}-PA"
        for _ in range(_ID_ATTEMPTS):
            candidate = f"{prefix}-{random.randint(10000, 99999)}"
            if not self.repository.exists(candidate):
                return candidate
        raise ValueError(
            f"Could not generate an unused traceId for {prefix} after "
            f"{_ID_ATTEMPTS} attempts."
        )

    def create_trace(
        self,
        subject_ref: str,
        decision_type: str = "PRIOR_AUTHORIZATION",
        subject_type: str = "MEMBER",
        triggered_by: str = "system:insurance_agent",
        guideline_ref: str = None,
        input_facts: str = None,
        requested_service: str = None,
    ) -> dict:
        """Insurance Agent, step 0: open an empty decision trace for a case.

        Every decision leaves one, whether it ends in an approval, a denial or an
        escalation. Nothing is decided here — `steps[]`, `outcome` and the review
        closure are all filled in later, by this agent for the administrative gates
        and by the care-coordination agent for the clinical ones.

        This is the only way a case is opened: the insurance agent creates the
        shell here at step 0 and attaches the `traceId` to the member's pending
        action, and the care-coordination agent picks it up from there.

        Also writes the two workflow fields `status` and `requested_service`, which
        the final data model does not define but this backend produces on every
        trace, so a case in flight can be told from a closed one.

        `input_facts` is a ";"-delimited string; empty parts are dropped.
        """
        if not self.member_repo.get_by_key(subject_ref) and subject_type == "MEMBER":
            raise LookupError(f"Member {subject_ref} not found")

        now = _now()
        facts = [f.strip() for f in (input_facts or "").split(";") if f.strip()]
        trace = {
            "traceId": self._mint_trace_id(now[:4]),
            "decisionType": decision_type,
            "subjectRef": subject_ref,
            "subjectType": subject_type,
            # Workflow fields — see the docstring. `status` tracks the lifecycle the
            # final model expresses through `outcome` + `review`.
            "requested_service": requested_service,
            "status": "pending",
            "audit": {
                "triggeredBy": triggered_by,
                "triggeredAt": now,
                "reviewRequired": False,
                "reviewRequiredReason": None,
                "regulatoryFlags": [],
                "retentionYears": 7,
            },
            "contextSnapshot": {
                "guidelineRef": guideline_ref or None,
                "inputFacts": facts,
            },
            "steps": [],
            "outcome": None,
            # Initialised rather than left null, so "nobody has closed this" is an
            # explicit fact from the moment the case opens.
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

        try:
            self.repository.insert_trace(trace)
        except DuplicateKeyError:
            trace["traceId"] = self._mint_trace_id(now[:4])
            self.repository.insert_trace(trace)
        return {k: v for k, v in trace.items() if k != "_id"}

    def append_step(
        self,
        trace_id: str,
        memory_type: str,
        name: str,
        detail: str,
        confidence: float,
        step_input=None,
        step_output=None,
        recorded_by: str = None,
    ) -> dict:
        """Record one reasoning step on a trace, tagged by memory type.

        `memory_type` is mandatory and validated: an untagged step would break the
        one property that makes this trace auditable rather than narrative. Note
        that tagging a step `episodic` or `procedural` has a consequence beyond
        labelling — it marks the determination as clinical, which removes the
        agent's authority to close it.

        `stepId` is assigned server-side, sequentially, so ids cannot collide or
        arrive out of order.

        `recorded_by` names the agent that produced the step. Two agents write to one
        trace, so an unattributed step leaves the record unable to say who reasoned
        what. Each agent's tool supplies its own identity.

        Raises LookupError for a missing trace (-> 404) and ValueError for an
        invalid memory type or a closed trace (-> 400).
        """
        memory_type = (memory_type or "").strip().lower()
        if memory_type not in MEMORY_TYPES:
            raise ValueError(
                f"memory_type must be one of {MEMORY_TYPES}, got {memory_type!r}. "
                "Every step must declare one."
            )
        trace = self.repository.get_by_key(trace_id)
        if not trace:
            raise LookupError(f"Trace {trace_id} not found")
        if (trace.get("review") or {}).get("closedBy"):
            raise ValueError(
                f"Trace {trace_id} was closed by "
                f"{(trace.get('review') or {}).get('closedBy')}; its reasoning is part of "
                "a finalized record and cannot be added to."
            )

        step = {
            "stepId": f"STP-{len(trace.get('steps') or []) + 1:03d}",
            "memoryType": memory_type,
            "recordedBy": recorded_by,
            "name": name,
            "input": _as_object(step_input),
            "output": _as_object(step_output),
            "confidence": confidence,
            "detail": detail,
        }
        self.repository.push_step(trace_id, step, {"updatedAt": _now()})
        return self.repository.get_by_key(trace_id)

    def record_recommendation(
        self,
        trace_id: str,
        decision: str,
        rationale: str,
        confidence: float,
    ) -> dict:
        """Care-coordination agent, step 7: record a proposed outcome on the trace.

        This is the write that makes a recommendation exist as data rather than as
        conversation. Until it lands, `route_decision` has nothing to route.

        **It recommends; it never closes.** `review.closedBy`, `review.routedToHuman`
        and `audit.reviewRequired` are deliberately untouched — who may close the case
        is decided afterwards by the bounded-authority check, reading this outcome
        together with whether any clinical reasoning is on the trace. Keeping the two
        apart is what stops a reasoner from closing its own case by writing a
        confident-looking outcome.

        Overwrites any previous recommendation rather than appending: a trace carries
        one current proposal, and its history is the `steps[]` that produced it.

        Raises LookupError for a missing trace (-> 404) and ValueError for an invalid
        decision, an out-of-range confidence, or a closed trace (-> 400).
        """
        decision = (decision or "").strip().lower()
        if decision not in RECOMMENDABLE_DECISIONS:
            raise ValueError(
                f"decision must be one of {RECOMMENDABLE_DECISIONS}, got {decision!r}."
            )
        if confidence is None or not 0.0 <= float(confidence) <= 1.0:
            raise ValueError(f"confidence must be between 0 and 1, got {confidence!r}.")
        if not (rationale or "").strip():
            raise ValueError(
                "rationale is required: an outcome a reviewer cannot read is not an "
                "auditable one."
            )

        trace = self.repository.get_by_key(trace_id)
        if not trace:
            raise LookupError(f"Trace {trace_id} not found")
        closed_by = (trace.get("review") or {}).get("closedBy")
        if closed_by:
            raise ValueError(
                f"Trace {trace_id} was closed by {closed_by}; its outcome is part of a "
                "finalized record and cannot be revised."
            )

        existing = trace.get("outcome") or {}
        trace["outcome"] = {
            "decision": decision,
            "rationale": rationale,
            "confidence": float(confidence),
            # An override is a human act recorded at closure. Carry any existing values
            # rather than resetting them, so re-recording a recommendation cannot erase
            # a medical director's override.
            "overrideFlag": existing.get("overrideFlag", False),
            "overrideBy": existing.get("overrideBy"),
            "overrideReason": existing.get("overrideReason"),
        }
        # Workflow field the backend reads for `summary.open_authorization_count`;
        # kept in step with `outcome.decision` in the same write so the two cannot drift.
        trace["status"] = decision
        trace["updatedAt"] = _now()
        self.repository.upsert(trace)
        return self.repository.get_by_key(trace_id)

    # --- bounded authority ---------------------------------------------------

    def _resolve_guideline(self, trace: dict) -> tuple:
        """Resolve the guideline behind a trace. Returns (guideline, source).

        Tries `contextSnapshot.guidelineRef` against `_id` first — which is what the
        reference is nominally for — then falls back to the newest guideline for the
        subject's diagnosis.

        The fallback exists because of a mismatch in the data: traces record refs
        like `CMG-RA-2026.3`, while guideline documents carry a MongoDB-assigned
        ObjectId `_id` and no field holding that string. So the ref cannot resolve
        today and the condition path is what actually answers. The consequence worth
        knowing: this reads the *newest* guideline for the condition, not the version
        the decision was made under, so it is not true version pinning. If a
        `guidelineId` business key is ever added, the first branch starts hitting and
        pinning becomes exact with no code change.
        """
        ref = (trace.get("contextSnapshot") or {}).get("guidelineRef")
        if ref:
            guideline = self.guideline_repo.get_by_id(ref)
            if guideline:
                return guideline, "guideline_ref"

        member = self.member_repo.get_by_key(trace.get("subjectRef")) or {}
        diagnoses = (member.get("clinical_history") or {}).get("diagnoses") or []
        active = [d for d in diagnoses if (d.get("status") or "active") == "active"]
        for diagnosis in active or diagnoses:
            guideline = self.guideline_repo.latest_for_condition(diagnosis.get("code"))
            if guideline:
                return guideline, "condition"
        return None, "default"

    def _threshold(self, trace: dict) -> tuple:
        """The confidence threshold this trace is judged against, and its source."""
        guideline, source = self._resolve_guideline(trace)
        if not guideline:
            return DEFAULT_CONFIDENCE_THRESHOLD, "default", None
        threshold = guideline.get("confidence_threshold")
        if threshold is None:
            return DEFAULT_CONFIDENCE_THRESHOLD, "default", str(guideline.get("_id"))
        return float(threshold), source, str(guideline.get("_id"))

    @staticmethod
    def _has_clinical_reasoning(trace: dict) -> bool:
        """Did clinical reasoning run on this trace?

        True when any step is tagged `episodic` or `procedural`. This is the test
        that separates a clinical determination from an administrative one, and so
        decides who may close the case. Derived from the trace's own contents rather
        than from a flag someone sets, because a flag can be wrong and the steps
        cannot.
        """
        return any(
            (step.get("memoryType") or "").strip().lower() in CLINICAL_MEMORY_TYPES
            for step in (trace.get("steps") or [])
        )

    def route_decision(self, trace_id: str) -> dict:
        """Insurance Agent, step 8: the bounded-authority checkpoint.

        Applies a fixed rule to the recommendation already on the trace:

        - a denial reached on clinical grounds goes to a medical director at any
          confidence — absolute, no exceptions;
        - anything below the guideline's threshold goes to a medical director,
          whichever way it leans;
        - everything else the agent may close itself.

        The confidence gate is deliberately **not** applied to administrative
        denials. An eligibility lapse or a benefit exclusion is a factual date/status
        comparison, and the data model's guardrail table makes those agent-closable
        unconditionally; routing one to a physician on a confidence technicality
        would put mechanical paperwork in a clinician's queue.

        Records its own verdict on the trace (`audit.reviewRequired`,
        `audit.reviewRequiredReason`, `review.finalDecisionMaker`) so the checkpoint
        is visible in the audit trail and so the closure endpoints can enforce it —
        but does **not** set `routedToHuman`, which is `escalate`'s job. That
        separation means "we determined this needs a human" and "we handed it to one"
        stay distinguishable.

        Raises LookupError for a missing trace (-> 404), ValueError when there is no
        recommendation to route (-> 400).
        """
        trace = self.repository.get_by_key(trace_id)
        if not trace:
            raise LookupError(f"Trace {trace_id} not found")

        outcome = trace.get("outcome") or {}
        decision = (outcome.get("decision") or "").strip().lower()
        if not decision:
            raise ValueError(
                f"Trace {trace_id} carries no outcome.decision, so there is no "
                "recommendation to route. Clinical review has not produced one yet."
            )

        confidence = outcome.get("confidence")
        threshold, source, guideline_id = self._threshold(trace)
        clinical = self._has_clinical_reasoning(trace)

        if decision == "denied" and clinical:
            reason = ESCALATION_CLINICAL_DENIAL
            detail = (
                f"Denial reached through clinical reasoning (episodic/procedural steps "
                f"are on trace {trace_id}). A medical director must close it, at any "
                "confidence. The agent has no authority to issue a clinical denial."
            )
        elif decision == "denied" and not clinical:
            reason = None
            detail = (
                f"Denial reached on administrative grounds — no clinical reasoning ran "
                f"on trace {trace_id}. A factual gate decided the case, so the agent may "
                "close it as an administrative determination."
            )
        elif decision == "pending":
            reason = ESCALATION_LOW_CONFIDENCE
            detail = (
                f"Trace {trace_id} records no settled recommendation (decision "
                "'pending'), which is itself a case for a human reviewer."
            )
        elif confidence is None or float(confidence) < threshold:
            reason = ESCALATION_LOW_CONFIDENCE
            detail = (
                f"Confidence {confidence} is below the guideline threshold {threshold}; "
                f"a medical director must close trace {trace_id}, regardless of which "
                "way the recommendation leans."
            )
        else:
            reason = None
            detail = (
                f"Recommendation {decision!r} with confidence {confidence} meets the "
                f"guideline threshold {threshold}. The agent may close trace {trace_id}."
            )

        must_escalate = reason is not None
        self.repository.update_fields(
            trace_id,
            {
                "audit.reviewRequired": must_escalate,
                "audit.reviewRequiredReason": reason,
                "review.finalDecisionMaker": (
                    "medical_director" if must_escalate else "agent"
                ),
                "updatedAt": _now(),
            },
        )

        return {
            "traceId": trace_id,
            "mayAgentClose": not must_escalate,
            "mustEscalate": must_escalate,
            "escalationReason": reason,
            "decision": decision,
            "confidence": confidence,
            "confidenceThreshold": threshold,
            "clinicalReasoningPresent": clinical,
            "guidelineRef": guideline_id,
            "thresholdSource": source,
            "detail": detail,
        }

    def _assert_closable(
        self, trace: dict, closed_by: str, require_outcome: bool = True
    ) -> dict:
        """Shared preconditions for both agent-closure paths.

        Each closure endpoint re-checks its own conditions rather than trusting
        `route_decision`'s verdict: a guardrail that can be bypassed by simply not
        calling the checkpoint first is not a guardrail.

        `require_outcome=False` is used by the administrative path, which records
        its own determination from the closure reason. An approval must always have
        been recommended by clinical review first, so that path keeps the check.
        """
        outcome = trace.get("outcome") or {}
        if require_outcome and not outcome.get("decision"):
            raise ValueError(
                f"Trace {trace['traceId']} has no recommendation on it yet. A case "
                "cannot be closed before it has been decided."
            )
        review = trace.get("review") or {}
        if review.get("closedBy"):
            raise ValueError(
                f"Trace {trace['traceId']} was already closed by {review['closedBy']}."
            )
        if review.get("routedToHuman") or (trace.get("audit") or {}).get("reviewRequired"):
            raise ValueError(
                f"Trace {trace['traceId']} is routed to "
                f"{review.get('finalDecisionMaker') or 'a human reviewer'}. Only that "
                "reviewer may close it, via POST /api/audit/traces/{trace_id}/close."
            )
        if not (closed_by or "").startswith("system:"):
            raise ValueError(
                f"closed_by must be a system identity for an agent closure, e.g. "
                f"'system:insurance_agent'; got {closed_by!r}. A human closure goes "
                "through the medical-director endpoint."
            )
        return outcome

    def _close(self, trace_id: str, decision: str, closed_by: str, flag: str = None) -> dict:
        """Persist an agent closure."""
        now = _now()
        updates = {
            "review.closedBy": closed_by,
            "review.closedAt": now,
            "review.finalDecisionMaker": "agent",
            "review.routedToHuman": False,
            "audit.reviewRequired": False,
            # Keep the workflow field in step with the outcome, so a closed trace
            # stops looking pending to `find_pending_by_member`.
            "status": decision,
            "updatedAt": now,
        }
        self.repository.update_fields(trace_id, updates)
        if flag:
            self.repository.collection.update_one(
                {"traceId": trace_id}, {"$addToSet": {"audit.regulatoryFlags": flag}}
            )
        trace = self.repository.get_by_key(trace_id)
        member = self.member_repo.get_by_key(trace.get("subjectRef"))
        if member:
            # An agent-closed approval has to move the care plan on, exactly as a
            # physician closure does: the member record is what the next request
            # reads, and leaving `approved_therapy` null after an approval makes the
            # record disagree with its own trace. `approved_restricted` counts — the
            # therapy was approved, only its stages are limited.
            if decision in APPROVAL_DECISIONS:
                therapy = self._resolve_therapy(trace, member)
                if therapy:
                    self._mark_approved_therapy(member, therapy)
            # Persists the care-plan edit above too; see `_recompute_summary`.
            self._recompute_summary(member)
        return trace

    def close_administrative(
        self, trace_id: str, reason: str, closed_by: str = "system:insurance_agent"
    ) -> dict:
        """Close a case as the agent — administrative determinations only.

        Permitted for exactly two grounds, both factual gates that fire before
        clinical review: `eligibility_lapsed` and `benefit_exclusion`.

        **Records the determination as part of closing it.** Nothing in the Insurance
        Agent's toolset writes `outcome` — that is step 7, which belongs to the
        clinical agent and never runs when the process short-circuits at step 1 or 2 —
        so requiring a pre-existing recommendation made every administrative denial
        unclosable. For a factual gate the reason IS the decision, and its rationale
        comes from `ADMIN_RATIONALES` rather than from the agent's prose, so the same
        gate is always described the same way.

        An outcome already on the trace is respected, not overwritten: if it says
        anything other than `denied`, this path refuses.

        **The clinical refusal is the literal implementation of bounded authority**,
        and it is checked BEFORE any outcome is written, so a refused closure leaves
        the trace exactly as it was. A 400 here is the correct answer rather than an
        obstacle — the case belongs to a medical director.

        Raises LookupError (-> 404) and ValueError (-> 400).
        """
        reason = (reason or "").strip().lower()
        if reason not in ADMIN_CLOSABLE_REASONS:
            raise ValueError(
                f"reason must be one of {ADMIN_CLOSABLE_REASONS}, got {reason!r}. "
                "Only factual, non-clinical determinations are agent-closable."
            )
        trace = self.repository.get_by_key(trace_id)
        if not trace:
            raise LookupError(f"Trace {trace_id} not found")

        outcome = self._assert_closable(trace, closed_by, require_outcome=False)
        decision = (outcome.get("decision") or "").strip().lower()
        if decision and decision != "denied":
            raise ValueError(
                f"Trace {trace_id} already records decision {decision!r}. An "
                "administrative determination on these grounds is a denial; use "
                "/close-authorization for an approval."
            )
        # Checked before writing anything: a refusal must leave the trace untouched.
        if self._has_clinical_reasoning(trace):
            raise ValueError(
                f"Trace {trace_id} carries clinical reasoning (episodic/procedural "
                "steps), so this denial is not an administrative determination. Only a "
                "medical director may close a clinical denial — escalate it instead."
            )

        if not decision:
            decision = "denied"
            self.repository.update_fields(
                trace_id,
                {
                    "outcome": {
                        "decision": decision,
                        "rationale": ADMIN_RATIONALES[reason],
                        "confidence": ADMIN_CONFIDENCE,
                        "overrideFlag": False,
                        "overrideBy": None,
                        "overrideReason": None,
                    }
                },
            )
        return self._close(trace_id, decision, closed_by, flag=reason)

    def close_authorization(
        self, trace_id: str, closed_by: str = "system:insurance_agent"
    ) -> dict:
        """Close a case as the agent — clinically-supported approvals only.

        Valid when the recommendation is `approved` or `approved_restricted` AND its
        confidence meets the guideline threshold. Both conditions are re-checked
        here; this path can never close a denial.

        Raises LookupError (-> 404) and ValueError (-> 400).
        """
        trace = self.repository.get_by_key(trace_id)
        if not trace:
            raise LookupError(f"Trace {trace_id} not found")

        outcome = self._assert_closable(trace, closed_by)
        decision = (outcome.get("decision") or "").strip().lower()
        if decision not in APPROVAL_DECISIONS:
            raise ValueError(
                f"Trace {trace_id} records decision {decision!r}; this path closes only "
                f"{APPROVAL_DECISIONS}. A denial is never closed here."
            )
        threshold, _source, _gid = self._threshold(trace)
        confidence = outcome.get("confidence")
        if confidence is None or float(confidence) < threshold:
            raise ValueError(
                f"Confidence {confidence} is below the guideline threshold {threshold}, "
                f"so trace {trace_id} must go to a medical director rather than close."
            )
        return self._close(trace_id, decision, closed_by)

    def escalate(
        self,
        trace_id: str,
        reason: str,
        case_brief: str = None,
        final_decision_maker: str = "medical_director",
    ) -> dict:
        """Route a case to a medical director and mark it awaiting human closure.

        Sets `audit.reviewRequired`, `review.routedToHuman` and
        `review.finalDecisionMaker`, and leaves `review.closedBy` null — that null is
        precisely how bounded authority is expressed in the data.

        The case does not end here, it pauses. `status` becomes `pending_review`, and
        the member's pending action must stay `in_progress` so the frontend can show
        "awaiting medical director" rather than "not started".

        Raises LookupError (-> 404) and ValueError (-> 400) if already closed.
        """
        if not (reason or "").strip():
            raise ValueError("reason is required: an escalation must record why.")
        trace = self.repository.get_by_key(trace_id)
        if not trace:
            raise LookupError(f"Trace {trace_id} not found")
        review = trace.get("review") or {}
        if review.get("closedBy"):
            raise ValueError(
                f"Trace {trace_id} was already closed by {review['closedBy']}; there is "
                "nothing to escalate."
            )

        now = _now()
        updates = {
            "audit.reviewRequired": True,
            "audit.reviewRequiredReason": reason,
            "review.routedToHuman": True,
            "review.finalDecisionMaker": final_decision_maker,
            # Explicitly held null: the agent has handed the case over, and only the
            # reviewer may fill this in.
            "review.closedBy": None,
            "status": "pending_review",
            "updatedAt": now,
        }
        if case_brief:
            updates["review.caseBrief"] = case_brief
        self.repository.update_fields(trace_id, updates)

        trace = self.repository.get_by_key(trace_id)
        member = self.member_repo.get_by_key(trace.get("subjectRef"))
        if member:
            self._recompute_summary(member)
        return trace

    # --- reads / human review -----------------------------------------------

    def get_trace(self, trace_id: str) -> dict:
        return self.repository.get_by_key(trace_id)

    def get_member_traces(self, member_id: str) -> list:
        return self.repository.find_by_member(member_id)

    def get_member_audit_trail(self, member_id: str) -> list:
        """Chronological decision traces for a member (regulator view)."""
        return self.repository.find_by_member(member_id)

    def get_pending_human_review(self) -> list:
        return self.repository.find_routed_to_human()

    def open_human_review(self, trace_id: str, medical_director_id: str = None) -> dict:
        """Phase 3a, step 2: assemble the brief for a medical director — the full
        trace plus the broader member clinical context.

        This is the one read that returns a raw document rather than going through
        a `response_model`, so `_id` is dropped explicitly: it is an ObjectId,
        which FastAPI's JSON encoder cannot serialize. Repository reads keep `_id`
        because `upsert` needs it, so the removal belongs here rather than in the
        projection.
        """
        trace = self.repository.get_by_key(trace_id)
        if not trace:
            raise ValueError(f"Trace {trace_id} not found")
        trace = {k: v for k, v in trace.items() if k != "_id"}

        member = self.member_repo.get_by_key(trace["subjectRef"]) or {}
        member_context = {
            "member_id": trace["subjectRef"],
            "name": f"{member.get('firstName', '')} {member.get('lastName', '')}".strip(),
            "eligibility": member.get("eligibility"),
            "clinical_history": member.get("clinical_history"),
            "current_care_plan": member.get("current_care_plan"),
        }
        return {"trace": trace, "member_context": member_context}

    def close_trace(
        self, trace_id: str, medical_director_id: str, decision: str, notes: str = None
    ) -> dict:
        """Phase 3a, step 3: a medical director sets the final decision.

        Only a trace routed to a human can be human-closed (bounded authority).
        Updates status + review closure + outcome override, recomputes the member
        summary, and notifies the member.
        """
        if decision not in ("approved", "denied"):
            raise ValueError("decision must be 'approved' or 'denied'")

        trace = self.repository.get_by_key(trace_id)
        if not trace:
            raise ValueError(f"Trace {trace_id} not found")
        review = trace.get("review") or {}
        if not review.get("routedToHuman"):
            raise ValueError("Trace was not routed to a human; nothing to close")
        if review.get("closedBy"):
            raise ValueError(f"Trace already closed by {review['closedBy']}")

        now = _now()
        trace["status"] = decision
        review["closedBy"] = medical_director_id
        review["closedAt"] = now
        if notes:
            review["notes"] = notes
        trace["review"] = review

        outcome = trace.setdefault("outcome", {})
        # If the physician diverged from the agent's recommendation, mark the override.
        if outcome.get("decision") and outcome["decision"] != decision:
            outcome["overrideFlag"] = True
            outcome["overrideBy"] = medical_director_id
            outcome["overrideReason"] = notes
        outcome["decision"] = decision
        trace["updatedAt"] = now
        self.repository.upsert(trace)

        member = self.member_repo.get_by_key(trace["subjectRef"])
        if member:
            if decision in APPROVAL_DECISIONS:
                therapy = self._resolve_therapy(trace, member)
                if therapy:
                    self._mark_approved_therapy(member, therapy)
            self._recompute_summary(member)

        # Notify the member of the final human decision (parity with the happy
        # path). Imported locally to avoid a module-level import cycle. A
        # notification failure must not roll back a completed physician decision.
        try:
            from notifications.service import NotificationService

            NotificationService(self._connector).notify_member(trace["subjectRef"])
        except Exception:
            pass

        return trace
