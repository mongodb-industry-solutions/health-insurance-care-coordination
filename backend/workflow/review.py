"""The medical director's decision, and the cascade it triggers.

The bounded-authority rule is that an agent may not close a clinical denial or a
low-confidence case. That rule is only half a system: something has to let the human
actually close it, or an escalated case stays open forever.

The authority check itself stays in `traces`: `TraceService.close_by_director` refuses a
trace that was never escalated and one that is already closed, as a compare-and-set on the
stage. What lives here is the *cascade*, which that call does not do and which now spans both
databases: the linked claim, the member's summary and the clinical record (the physician's
order is resolved, and an approval writes `approved_therapy`). A case that looks undecided on
the member's record is not closed in any sense that matters to the person waiting for
treatment.

The queue and the brief each case carries live in `views/review.py`: they join both databases
and are assembled at read time.
"""

import logging

from clinical.profiles.service import ProfileService
from db.mdb import MongoDBConnector
from insurance.claims.repository import ClaimRepository
from insurance.claims.service import ClaimService
from insurance.members.service import MemberService
from traces.service import PHYSICIAN_DECISIONS, TraceService

from .clinical_sync import ClinicalSync

logger = logging.getLogger(__name__)

# Claim status per recorded decision. `approved_restricted` follows from the plan's benefit
# design (`administrativeGates.coverageRestriction`), not from the physician's judgement; the
# trace service records it when a physician approves a partially-covered case.
_CLAIM_STATUS = {
    "approved": "approved",
    "approved_restricted": "approved_restricted",
    "denied": "denied",
}


class MedicalDirectorReviewService:
    def __init__(self, insurance: MongoDBConnector, clinical: MongoDBConnector):
        self.traces = TraceService(insurance)
        self.claims = ClaimService(insurance)
        self.claim_repo = ClaimRepository(insurance)
        self.members = MemberService(insurance)
        self.profiles = ProfileService(clinical)
        self.sync = ClinicalSync(self.profiles)

    def _linked_claim_id(self, member_id: str, trace_id: str) -> str:
        """The `claimId` of the claim this trace decided, if there is one. Only `claimId`,
        never `_id`: the repository keys on the business id."""
        for claim in self.claim_repo.find_by_trace(trace_id) or []:
            if claim.get("claimId"):
                return claim["claimId"]
        # Claims opened before the agent stamped them at creation carry no link yet.
        for claim in self.claim_repo.find_by_member(member_id) or []:
            if claim.get("linkedAuditTraceId") == trace_id:
                return claim.get("claimId")
        return None

    def decide(
        self,
        trace_id: str,
        medical_director_id: str,
        decision: str,
        notes: str = None,
        member_owed: float = 0,
        paid_amt: float = 0,
    ) -> dict:
        """Close an escalated case as the medical director, then cascade.

        Order is not incidental. The trace closes first because
        `ClaimService.update_claim_status` refuses to set a decided status unless the linked
        trace is already closed with that decision: the claim and its trace must tell the
        same story.

        The cascade is best-effort *after* the physician's decision is recorded: a claim,
        summary or clinical write that fails must not unwind a completed decision, so
        failures are reported in the response rather than raised.

        Raises LookupError for an unknown trace and ValueError for an invalid decision, a
        case not escalated, or one already closed (-> HTTP 404 / 400 at the route).
        """
        decision = (decision or "").strip().lower()
        if decision not in PHYSICIAN_DECISIONS:
            raise ValueError(f"decision must be one of {PHYSICIAN_DECISIONS}, got {decision!r}")

        trace = self.traces.get_trace(trace_id)
        if not trace:
            raise LookupError(f"Trace {trace_id} not found")

        member_id = trace.get("subjectRef")
        agent_recommendation = (trace.get("outcome") or {}).get("decision")

        # Bounded authority lives here: refuses a trace never escalated, and one already
        # closed. Also records the override when the physician diverges from the agent.
        closed = self.traces.close_by_director(
            trace_id,
            medical_director_id=medical_director_id,
            decision=decision,
            notes=notes,
        )
        recorded = (closed.get("outcome") or {}).get("decision")

        cascade = {"claim": None, "member_summary": None, "pending_action": None,
                   "approved_therapy": None, "errors": []}

        claim_id = self._linked_claim_id(member_id, trace_id)
        if claim_id:
            try:
                self.claims.update_claim_status(
                    claim_id,
                    status=_CLAIM_STATUS[recorded],
                    paid_amt=paid_amt,
                    member_owed=member_owed,
                    denial_reason=("medical_necessity" if recorded == "denied" else None),
                    linked_audit_trace_id=trace_id,
                )
                cascade["claim"] = {"claim_id": claim_id, "status": _CLAIM_STATUS[recorded]}
            except Exception as e:  # noqa: BLE001
                logger.error("claim %s not updated after review of %s: %s", claim_id, trace_id, e)
                cascade["errors"].append(f"claim {claim_id}: {e}")
        else:
            cascade["errors"].append(f"no claim links to trace {trace_id}")

        try:
            summary = self.members.recompute_summary(member_id)
            cascade["member_summary"] = (summary or {}).get("summary")
        except Exception as e:  # noqa: BLE001
            logger.error("summary not refreshed for %s after review of %s: %s", member_id, trace_id, e)
            cascade["errors"].append(f"member summary {member_id}: {e}")

        try:
            changed = self.sync.sync_case(closed)
            action_id = (closed.get("request") or {}).get("actionId")
            if action_id:
                cascade["pending_action"] = {"action_id": action_id, "status": "resolved"}
            cascade["approved_therapy"] = bool(changed.get("approved_therapy"))
            if not action_id:
                cascade["errors"].append(f"trace {trace_id} names no pending action to resolve")
        except Exception as e:  # noqa: BLE001
            logger.error("clinical sync failed after review of %s: %s", trace_id, e)
            cascade["errors"].append(f"clinical record {member_id}: {e}")

        review = closed.get("review") or {}
        outcome = closed.get("outcome") or {}
        return {
            "trace_id": trace_id,
            "member_id": member_id,
            "status": closed.get("status"),
            "decision": outcome.get("decision"),
            "agent_recommendation": agent_recommendation,
            # True when the physician did not follow the agent. The single most important
            # number in this endpoint for anyone auditing the system.
            "override": bool(outcome.get("overrideFlag")),
            "override_reason": outcome.get("overrideReason"),
            "closed_by": review.get("closedBy"),
            "closed_at": review.get("closedAt"),
            "notes": review.get("notes"),
            "claim": cascade["claim"],
            "pending_action": cascade["pending_action"],
            "member_summary": cascade["member_summary"],
            "approved_therapy_recorded": cascade["approved_therapy"],
            "cascade_errors": cascade["errors"],
            "detail": (
                f"Trace {trace_id} closed {outcome.get('decision')} by "
                f"{review.get('closedBy')}"
                + (
                    f", overriding the agent's {agent_recommendation!r} recommendation."
                    if outcome.get("overrideFlag")
                    else f", concurring with the agent's {agent_recommendation!r} recommendation."
                )
            ),
        }
