"""Business logic for authorization decisions and bounded authority."""

import uuid
from datetime import datetime, timezone

from db.mdb import get_connector
from .repository import AuthorizationRepository
from members.repository import MemberRepository
from guidelines.repository import GuidelineRepository
from plans.repository import PlanRepository
from claims.service import ClaimService
from audit.repository import AuditRepository


class AuthorizationService:
    """Service layer for authorization decisions.

    Orchestrates member context, guidelines, comparable cases, and audit logging
    to build complete authorization decisions with decision traces.
    """

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.auth_repo = AuthorizationRepository(connector)
        self.member_repo = MemberRepository(connector)
        self.guideline_repo = GuidelineRepository(connector)
        self.plan_repo = PlanRepository(connector)
        # Sibling service (not repo) for claim analysis — reuses comparable-case
        # and refill-gap logic instead of duplicating it here.
        self.claim_service = ClaimService(connector)
        self.audit_repo = AuditRepository(connector)

    def file_authorization(
        self, member_id: str, requested_service: str
    ) -> dict:
        """Phase 3, step 1: file a formal authorization request.

        Creates a minimal `pending` authorization — no decision_trace or review
        yet; those are populated when it is processed (step 2). This is the EHR/
        provider filing the request, not an agent decision. A unique id is used so
        a member can hold multiple authorizations over time (no clobbering). Logs
        the step-1a audit (`authorization filed`). Raises ValueError if the member
        does not exist.
        """
        if not self.member_repo.get_by_id(member_id):
            raise ValueError(f"Member {member_id} not found")

        auth_id = f"AUTH-{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        authorization = {
            "_id": auth_id,
            "member_id": member_id,
            "requested_service": requested_service,
            "status": "pending",
            "created_at": now,
            "decision_trace": None,
            "review": None,
        }
        self.auth_repo.upsert(authorization)

        self.audit_repo.record(
            member_id=member_id,
            agent="ehr_integration",
            action="authorization filed",
            fields_accessed=["authorizations"],
            related_authorization=auth_id,
        )
        return authorization

    def process_authorization(self, member_id: str) -> dict:
        """Phase 3, step 2: process the member's pending authorization.

        Deterministically computes the decision from the member's CURRENT record
        (which the pathway + verification agents already shaped), the guideline, and
        comparable precedent, then applies bounded authority. Populates the
        decision_trace with a *computed* confidence (no faked literals), updates the
        authorization, recomputes the member summary (2a), and audits the decision
        (2b). Raises ValueError if there is no pending authorization.
        """
        auth = self.auth_repo.find_pending_by_member(member_id)
        if not auth:
            raise ValueError(f"No pending authorization for member {member_id}")
        member = self.member_repo.get_by_id(member_id)
        if not member:
            raise ValueError(f"Member {member_id} not found")

        # --- Assemble the facts (from the current record) --------------------
        requested_service = auth["requested_service"]
        therapy = (
            member.get("current_care_plan", {}).get("considering_therapy")
            or requested_service.replace("biologic therapy - ", "")
        )
        diagnoses = member.get("clinical_history", {}).get("diagnoses", [])
        diagnosis_code = diagnoses[0]["code"] if diagnoses else None
        guideline = self.guideline_repo.latest_for_condition(diagnosis_code) or {}

        eligible = member.get("eligibility", {}).get("status") == "active"
        therapy_tier = guideline.get("classification", {}).get(therapy, {}).get("tier")
        tier_covered = self._tier_covered(member, therapy_tier)
        step_met, step_note = self._step_therapy_met(member, guideline)
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

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        auth["status"] = status
        auth["decision_trace"] = {
            "context_assembled": self._context(
                eligible, therapy_tier, tier_covered, member.get("plan_id"),
                step_note, comparable, gaps, unresolved_gap,
            ),
            "guideline_version": guideline.get("_id", "unknown"),
            "reasoning": reasoning,
            "agent_confidence": confidence,
        }
        auth["review"] = {
            "routed_to_human": routed_to_human,
            "final_decision_maker": "medical_director" if routed_to_human else "agent",
            "closed_by": None if routed_to_human else "pathway_agent",
            "closed_at": None if routed_to_human else now,
        }
        self.auth_repo.upsert(auth)

        if status == "approved" and not routed_to_human:
            self._mark_approved_therapy(member, therapy)
        self._recompute_summary(member)  # 2a
        self.audit_repo.record(  # 2b
            member_id=member_id,
            agent="pathway_agent",
            action="authorization decided",
            fields_accessed=["authorizations", "clinical_history", "eligibility"],
            related_authorization=auth["_id"],
        )
        return auth

    # --- decision helpers ----------------------------------------------------

    def _tier_covered(self, member: dict, therapy_tier: str) -> bool:
        """Does the member's plan cover the tier the requested therapy sits in?"""
        if not therapy_tier:
            return True
        plan = self.plan_repo.get_by_id(member.get("plan_id")) or {}
        tiers = plan.get("coverage", {}).get("tiers", {})
        return bool(tiers.get(therapy_tier, {}).get("covered"))

    def _step_therapy_met(self, member: dict, guideline: dict) -> tuple:
        """Step therapy is met if the LONGEST documented trial of the required drug
        meets the minimum (uses max across entries — the trajectory may hold several
        assessments, e.g. an interim 'ongoing' plus a later 'inadequate')."""
        st = guideline.get("criteria", {}).get("step_therapy", {})
        if not st:
            return True, "no step therapy requirement"
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
        )

    def _has_gap_review(self, member: dict) -> bool:
        return any(
            r.get("outcome") == "gap_reviewed"
            for r in member.get("clinical_history", {}).get("treatment_responses", [])
        )

    def _decide(self, eligible, therapy_tier, tier_covered, step_met,
                comparable_count, unresolved_gap, threshold) -> tuple:
        """Return (status, routed_to_human, confidence, reasoning).

        Hard administrative gates first (eligibility, benefit coverage) — factual
        denials the agent can close. Then the clinical path: a computed, transparent
        confidence gates auto-approval; clinical denials and low-confidence
        approvals route to a human. Denials are never auto-issued on clinical
        grounds.
        """
        if not eligible:
            return ("denied", False, 0.99,
                    "Member not eligible (coverage termed). Administrative "
                    "determination — no clinical review required.")
        if therapy_tier and not tier_covered:
            return ("denied", False, 0.99,
                    f"Plan does not cover the {therapy_tier} tier this therapy "
                    "requires. Benefit exclusion — administrative determination.")

        # Clinical path: transparent confidence from the evidence.
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

    def _context(self, eligible, therapy_tier, tier_covered, plan_id,
                 step_note, comparable, gaps, unresolved_gap) -> list:
        ctx = [
            f"eligibility: coverage {'active' if eligible else 'TERMED'}",
            f"benefit: {therapy_tier or 'n/a'} tier "
            f"{'covered' if tier_covered else 'NOT covered'} under plan {plan_id}",
            step_note,
        ]
        if comparable:
            ctx.append(
                "comparable cases: "
                + ", ".join(c["_id"] for c in comparable)
                + " (approved, similar presentation)"
            )
        else:
            ctx.append("comparable cases: none found")
        if gaps:
            ctx.append(
                f"refill gap: {len(gaps)} detected — "
                f"{'UNRESOLVED' if unresolved_gap else 'resolved'}"
            )
        return ctx

    def _mark_approved_therapy(self, member: dict, therapy: str) -> None:
        """On a finalized approval, reflect the approved therapy on the care plan
        (it is no longer merely being 'considered')."""
        cp = member.setdefault("current_care_plan", {})
        cp["approved_therapy"] = therapy
        cp["considering_therapy"] = None

    def _recompute_summary(self, member: dict) -> None:
        """Phase 3, step 2a: recompute the member's small cross-domain summary."""
        auths = self.auth_repo.find_by_member(member["_id"])
        open_count = sum(1 for a in auths if a.get("status") in ("pending", "pending_review"))
        last_status = auths[-1]["status"] if auths else "none"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        summary = member.setdefault("summary", {})
        summary["open_authorization_count"] = open_count
        summary["last_authorization_status"] = last_status
        summary["updated_at"] = now
        member["updated_at"] = now
        self.member_repo.upsert(member)

    def get_authorization(self, auth_id: str) -> dict:
        """Retrieve a specific authorization."""
        return self.auth_repo.get_by_id(auth_id)

    def get_member_authorizations(self, member_id: str) -> list:
        """Retrieve all authorizations for a member."""
        return self.auth_repo.find_by_member(member_id)

    def get_pending_human_review(self) -> list:
        """Retrieve all authorizations pending medical director review."""
        return self.auth_repo.find_routed_to_human()

    def open_human_review(self, auth_id: str, medical_director_id: str = None) -> dict:
        """Phase 3a, step 2/2a: assemble the brief for a medical director.

        Returns the full authorization (with its decision_trace) plus the broader
        member clinical context. When a `medical_director_id` is supplied, logs
        `human review opened` (2a). Raises ValueError if the authorization is
        unknown.
        """
        auth = self.auth_repo.get_by_id(auth_id)
        if not auth:
            raise ValueError(f"Authorization {auth_id} not found")

        member = self.member_repo.get_by_id(auth["member_id"]) or {}
        member_context = {
            "member_id": auth["member_id"],
            "demographics": member.get("demographics"),
            "eligibility": member.get("eligibility"),
            "clinical_history": member.get("clinical_history"),
            "current_care_plan": member.get("current_care_plan"),
        }
        if medical_director_id:
            self.audit_repo.record(
                member_id=auth["member_id"],
                agent=medical_director_id,
                action="human review opened",
                fields_accessed=["authorizations", "clinical_history", "eligibility"],
                related_authorization=auth_id,
            )
        return {"authorization": auth, "member_context": member_context}

    def close_authorization(
        self, auth_id: str, medical_director_id: str, decision: str, notes: str = None
    ) -> dict:
        """Phase 3a, step 3/3a/3b: a medical director sets the final decision.

        Only an authorization routed to a human can be human-closed (bounded
        authority — the agent never issues the final denial). Updates status +
        `closed_by`/`closed_at`, recomputes the member summary (3a), and audits
        `authorization closed by human` under the director's id (3b).
        """
        if decision not in ("approved", "denied"):
            raise ValueError("decision must be 'approved' or 'denied'")

        auth = self.auth_repo.get_by_id(auth_id)
        if not auth:
            raise ValueError(f"Authorization {auth_id} not found")
        review = auth.get("review") or {}
        if not review.get("routed_to_human"):
            raise ValueError("Authorization was not routed to a human; nothing to close")
        if review.get("closed_by"):
            raise ValueError(f"Authorization already closed by {review['closed_by']}")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        auth["status"] = decision
        review["closed_by"] = medical_director_id
        review["closed_at"] = now
        if notes:
            review["notes"] = notes
        auth["review"] = review
        self.auth_repo.upsert(auth)

        member = self.member_repo.get_by_id(auth["member_id"])
        if member:
            if decision == "approved":
                therapy = auth.get("requested_service", "").replace("biologic therapy - ", "")
                self._mark_approved_therapy(member, therapy)
            self._recompute_summary(member)  # 3a

        self.audit_repo.record(  # 3b
            member_id=auth["member_id"],
            agent=medical_director_id,
            action="authorization closed by human",
            fields_accessed=["authorizations.status", "authorizations.review"],
            related_authorization=auth_id,
        )
        return auth
