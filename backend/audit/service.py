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

import uuid
from datetime import datetime, timezone

from db.mdb import get_connector
from .repository import AuditRepository
from members.repository import MemberRepository
from policies.repository import PolicyRepository
from plans.repository import PlanRepository
from guidelines.repository import GuidelineRepository
from claims.service import ClaimService


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    # --- lifecycle -----------------------------------------------------------

    def file_trace(self, member_id: str, requested_service: str) -> dict:
        """Phase 3, step 1: file a formal prior-authorization request.

        Creates a `pending` trace — no steps/outcome/review yet; those are filled
        when it is processed. This is the EHR/provider filing the request, not an
        agent decision. Raises ValueError if the member does not exist.
        """
        if not self.member_repo.get_by_id(member_id):
            raise ValueError(f"Member {member_id} not found")

        trace_id = f"TRC-{uuid.uuid4().hex[:10].upper()}"
        now = _now()
        trace = {
            "_id": trace_id,
            "traceId": trace_id,
            "decisionType": "PRIOR_AUTHORIZATION",
            "subjectRef": member_id,
            "subjectType": "MEMBER",
            "requested_service": requested_service,
            "status": "pending",
            "audit": {
                "triggeredBy": "system:ehr_integration",
                "triggeredAt": now,
                "reviewRequired": False,
                "regulatoryFlags": ["CMS-PA-RULE"],
                "retentionYears": 7,
            },
            "contextSnapshot": None,
            "steps": [],
            "outcome": None,
            "review": None,
            "linkedTraces": [],
            "createdAt": now,
            "updatedAt": now,
        }
        self.repository.upsert(trace)
        return trace

    def process_trace(self, member_id: str) -> dict:
        """Phase 3, step 2: process the member's pending prior-auth trace.

        Deterministically computes the decision from the member's CURRENT record,
        the guideline, and comparable precedent, then applies bounded authority.
        Records the memory-typed `steps[]`, `contextSnapshot`, `outcome`, and
        `review`, and recomputes the member summary. Raises ValueError if there is
        no pending trace.
        """
        trace = self.repository.find_pending_by_member(member_id)
        if not trace:
            raise ValueError(f"No pending authorization for member {member_id}")
        member = self.member_repo.get_by_id(member_id)
        if not member:
            raise ValueError(f"Member {member_id} not found")

        # --- Assemble the facts (from the current record) --------------------
        requested_service = trace["requested_service"]
        therapy = (
            member.get("current_care_plan", {}).get("considering_therapy")
            or requested_service.replace("biologic therapy - ", "")
        )
        diagnoses = member.get("clinical_history", {}).get("diagnoses", [])
        diagnosis_code = diagnoses[0]["code"] if diagnoses else None
        guideline = self.guideline_repo.latest_for_condition(diagnosis_code) or {}

        eligible = member.get("eligibility", {}).get("status") == "active"
        therapy_tier = guideline.get("classification", {}).get(therapy, {}).get("tier")
        tier_covered, matched_treatment = self._coverage(
            member, therapy, diagnosis_code, therapy_tier
        )
        step_met, step_note, best_months, min_months, step_drug = self._step_therapy_met(
            member, guideline
        )
        comparable = self.claim_service.find_comparable_cases(
            requested_service, diagnosis_code, member_id=member_id
        )
        gaps = self.claim_service.detect_refill_gaps(member_id)["gaps"]
        unresolved_gap = bool(gaps) and not self._has_gap_review(member)
        threshold = guideline.get("confidence_threshold", 0.90)

        # --- Decide (transparent, computed) ----------------------------------
        status, routed_to_human, confidence, reasoning = self._decide(
            eligible, therapy_tier, tier_covered, step_met,
            len(comparable), unresolved_gap, threshold,
        )
        decision = "approved" if status == "approved" else (
            "denied" if status == "denied" else "pending"
        )

        now = _now()
        trace["status"] = status
        trace["contextSnapshot"] = {
            "guidelineRef": guideline.get("_id", "unknown"),
            "inputFacts": self._input_facts(
                eligible, therapy_tier, tier_covered, member.get("policyId"),
                step_note, comparable, gaps, unresolved_gap, matched_treatment,
            ),
        }
        trace["steps"] = self._build_steps(
            therapy, diagnosis_code, therapy_tier, tier_covered,
            step_drug, best_months, min_months, step_met, comparable,
        )
        trace["outcome"] = {
            "decision": decision,
            "rationale": reasoning,
            "confidence": confidence,
            "overrideFlag": False,
        }
        trace["review"] = {
            "routedToHuman": routed_to_human,
            "finalDecisionMaker": "medical_director" if routed_to_human else "agent",
            "closedBy": None if routed_to_human else "pathway_agent",
            "closedAt": None if routed_to_human else now,
        }
        meta = trace.setdefault("audit", {})
        meta["reviewRequired"] = routed_to_human
        if routed_to_human:
            meta["reviewRequiredReason"] = (
                "clinical_denial_requires_physician_closure" if status == "denied"
                else "confidence_below_threshold"
            )
        trace["updatedAt"] = now
        self.repository.upsert(trace)

        if status == "approved" and not routed_to_human:
            self._mark_approved_therapy(member, therapy)
        self._recompute_summary(member)  # 2a
        return trace

    # --- decision helpers ----------------------------------------------------

    def _resolve_plan(self, member: dict) -> dict:
        """member -> policy -> plan."""
        policy = self.policy_repo.get_by_id(member.get("policyId")) or {}
        return self.plan_repo.get_by_id(policy.get("planId")) or {}

    def _coverage(self, member: dict, therapy: str, diagnosis_code: str,
                  therapy_tier: str) -> tuple:
        """Does the member's plan cover the requested therapy? Returns
        (covered, matched_treatment_or_None).

        Treatment-level lookup first: match a plan `treatments[]` entry by `drug`
        (+ `condition` when the treatment scopes one). That entry's `covered` flag
        is authoritative — a plan can cover the specialty tier generally yet include
        or exclude a specific biologic. Falls back to tier-level coverage when the
        therapy has no explicit treatment entry (backward compatible).
        """
        plan = self._resolve_plan(member)
        therapy_l = (therapy or "").lower()
        for t in plan.get("treatments", []):
            if t.get("drug", "").lower() != therapy_l:
                continue
            if t.get("condition") and diagnosis_code and t["condition"] != diagnosis_code:
                continue
            return bool(t.get("covered")), t

        # No treatment-level entry — fall back to the tier flag.
        if not therapy_tier:
            return True, None
        tiers = plan.get("coverage", {}).get("tiers", {})
        return bool(tiers.get(therapy_tier, {}).get("covered")), None

    def _step_therapy_met(self, member: dict, guideline: dict) -> tuple:
        """Step therapy met if the LONGEST documented trial of the required drug
        meets the minimum. Returns (met, note, best_months, min_months, drug)."""
        st = guideline.get("criteria", {}).get("step_therapy", {})
        if not st:
            return True, "no step therapy requirement", 0, 0, None
        drug = st.get("drug")
        min_months = st.get("min_months", 6)
        durations = [
            r.get("duration_months", 0)
            for r in member.get("clinical_history", {}).get("treatment_responses", [])
            if r.get("drug") == drug
        ]
        best = max(durations) if durations else 0
        met = best >= min_months
        return met, (
            f"step therapy: {drug} {best} months documented vs {min_months} required — "
            f"{'satisfied' if met else 'NOT satisfied'}"
        ), best, min_months, drug

    def _has_gap_review(self, member: dict) -> bool:
        return any(
            r.get("outcome") == "gap_reviewed"
            for r in member.get("clinical_history", {}).get("treatment_responses", [])
        )

    def _decide(self, eligible, therapy_tier, tier_covered, step_met,
                comparable_count, unresolved_gap, threshold) -> tuple:
        """Return (status, routed_to_human, confidence, reasoning). Unchanged
        bounded-authority logic ported from the former authorization service."""
        if not eligible:
            return ("denied", False, 0.99,
                    "Member not eligible (coverage termed). Administrative "
                    "determination — no clinical review required.")
        if therapy_tier and not tier_covered:
            return ("denied", False, 0.99,
                    f"Plan does not cover the {therapy_tier} tier this therapy "
                    "requires. Benefit exclusion — administrative determination.")

        confidence = 0.0
        if step_met:
            confidence += 0.60
        if tier_covered:
            confidence += 0.15
        confidence += min(comparable_count, 2) * 0.10
        if unresolved_gap:
            confidence -= 0.15
        confidence = round(min(max(confidence, 0.0), 0.99), 2)

        if not step_met:
            return ("denied", True, confidence,
                    "Step therapy not satisfied. Denial recommended — a medical "
                    "director must make the final call. Agents never deny alone.")
        if confidence >= threshold:
            return ("approved", False, confidence,
                    f"All criteria satisfied; confidence {confidence} >= threshold "
                    f"{threshold}. Auto-approved.")
        return ("pending_review", True, confidence,
                f"Criteria met but confidence {confidence} < threshold {threshold} "
                "(e.g. no comparable precedent, or unresolved anomaly). Routed to a "
                "medical director.")

    def _build_steps(self, therapy, diagnosis_code, therapy_tier, tier_covered,
                     step_drug, best_months, min_months, step_met, comparable) -> list:
        """The memory-typed reasoning trail — the demo's core claim as data."""
        steps = [
            {
                "stepId": "STP-001",
                "memoryType": "semantic",
                "name": "match therapy to condition",
                "detail": f"Matched requested therapy {therapy} to condition {diagnosis_code}.",
                "confidence": 0.98,
            },
            {
                "stepId": "STP-002",
                "memoryType": "taxonomic",
                "name": "classify therapy",
                "detail": (
                    f"Classified {therapy} as {therapy_tier or 'n/a'} tier; "
                    f"plan coverage of that tier: {'yes' if tier_covered else 'no'}."
                ),
                "confidence": 0.97,
            },
            {
                "stepId": "STP-003",
                "memoryType": "episodic",
                "name": "member trial + comparable cases",
                "detail": (
                    f"Member trial: {step_drug} {best_months} months documented. "
                    + (
                        "Comparable approved cases: "
                        + ", ".join(c["_id"] for c in comparable)
                        if comparable else "No comparable approved precedent found."
                    )
                ),
                "confidence": 0.95,
            },
            {
                "stepId": "STP-004",
                "memoryType": "procedural",
                "name": "apply step-therapy gate",
                "detail": (
                    f"Step therapy requires {min_months} months; {best_months} documented — "
                    f"{'satisfied' if step_met else 'not satisfied'}."
                ),
                "confidence": 0.90,
            },
        ]
        return steps

    def _input_facts(self, eligible, therapy_tier, tier_covered, policy_id,
                     step_note, comparable, gaps, unresolved_gap,
                     matched_treatment=None) -> list:
        facts = [
            f"eligibility: coverage {'active' if eligible else 'TERMED'}",
            f"benefit: {therapy_tier or 'n/a'} tier "
            f"{'covered' if tier_covered else 'NOT covered'} under policy {policy_id}",
            step_note,
        ]
        if matched_treatment is not None:
            facts.append(
                f"plan treatment {matched_treatment.get('treatmentCode', '')} "
                f"({matched_treatment.get('drug')}): "
                f"{'COVERED' if matched_treatment.get('covered') else 'NOT covered'} "
                f"per plan formulary"
            )
        if comparable:
            facts.append(
                "comparable cases: "
                + ", ".join(c["_id"] for c in comparable)
                + " (approved, similar presentation)"
            )
        else:
            facts.append("comparable cases: none found")
        if gaps:
            facts.append(
                f"refill gap: {len(gaps)} detected — "
                f"{'UNRESOLVED' if unresolved_gap else 'resolved'}"
            )
        return facts

    def _mark_approved_therapy(self, member: dict, therapy: str) -> None:
        cp = member.setdefault("current_care_plan", {})
        cp["approved_therapy"] = therapy
        cp["considering_therapy"] = None

    def _recompute_summary(self, member: dict) -> None:
        """Recompute the member's small cross-domain summary from their traces."""
        traces = self.repository.find_by_member(member["_id"])
        open_count = sum(
            1 for t in traces if t.get("status") in ("pending", "pending_review")
        )
        last_status = traces[-1]["status"] if traces else "none"
        now = _now()
        summary = member.setdefault("summary", {})
        summary["open_authorization_count"] = open_count
        summary["last_authorization_status"] = last_status
        summary["updated_at"] = now
        member["updatedAt"] = now
        self.member_repo.upsert(member)

    # --- reads / human review -----------------------------------------------

    def get_trace(self, trace_id: str) -> dict:
        return self.repository.get_by_id(trace_id)

    def get_member_traces(self, member_id: str) -> list:
        return self.repository.find_by_member(member_id)

    def get_member_audit_trail(self, member_id: str) -> list:
        """Chronological decision traces for a member (regulator view)."""
        return self.repository.find_by_member(member_id)

    def get_pending_human_review(self) -> list:
        return self.repository.find_routed_to_human()

    def open_human_review(self, trace_id: str, medical_director_id: str = None) -> dict:
        """Phase 3a, step 2: assemble the brief for a medical director — the full
        trace plus the broader member clinical context."""
        trace = self.repository.get_by_id(trace_id)
        if not trace:
            raise ValueError(f"Trace {trace_id} not found")

        member = self.member_repo.get_by_id(trace["subjectRef"]) or {}
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

        trace = self.repository.get_by_id(trace_id)
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

        member = self.member_repo.get_by_id(trace["subjectRef"])
        if member:
            if decision == "approved":
                therapy = trace.get("requested_service", "").replace("biologic therapy - ", "")
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
