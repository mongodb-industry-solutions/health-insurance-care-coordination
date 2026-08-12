"""The medical director's decision, and the queue they work from.

The bounded-authority rule is that an agent may not close a clinical denial or a
low-confidence case. That rule is only half a system: something has to let the human
actually close it, or David's and Aisha's cases stay open forever.

The authority check itself stays in `audit` — `AuditService.close_trace` refuses a
trace that was never routed to a human and one that is already closed. What lives
here is the *cascade*, which `close_trace` does not do: the linked claim and the
member's pending action both still read "in flight" after a physician has decided,
and a case that looks undecided on the member's record is not closed in any sense
that matters to the person waiting for treatment.
"""

import logging

from db.mdb import MongoDBConnector
from audit.service import AuditService
from audit.repository import AuditRepository
from claims.service import ClaimService
from claims.repository import ClaimRepository
from members.service import MemberService

logger = logging.getLogger(__name__)

# What a physician may decide. Deliberately narrower than the claim model, which also
# knows `approved_restricted` and `paid`: a restricted approval follows from the plan's
# benefit design at Step 2, not from a clinical judgement, and `paid` is an
# adjudication outcome this demo never reaches.
PHYSICIAN_DECISIONS = ("approved", "denied")

# Claim status per decision.
_CLAIM_STATUS = {"approved": "approved", "denied": "denied"}


class MedicalDirectorReviewService:
    def __init__(self, connector: MongoDBConnector):
        self._connector = connector
        self.audit = AuditService(connector)
        self.traces = AuditRepository(connector)
        self.claims = ClaimService(connector)
        self.claim_repo = ClaimRepository(connector)
        self.members = MemberService(connector)

    # --- the queue ------------------------------------------------------------

    def pending_review(self) -> dict:
        """Every case waiting on a medical director.

        Derived from `review.routedToHuman` with `review.closedBy` still null — the
        state itself, not a flag someone maintains. Each entry carries the case brief
        the agent assembled, because that is the point of the escalation: the reviewer
        starts from an organised case rather than a raw record.
        """
        traces = self.traces.find_routed_to_human() or []
        traces.sort(key=lambda t: t.get("updatedAt") or t.get("createdAt") or "")

        queue = []
        for trace in traces:
            outcome = trace.get("outcome") or {}
            review = trace.get("review") or {}
            member = self.members.get_member(trace.get("subjectRef")) or {}
            queue.append({
                "trace_id": trace.get("traceId"),
                "member_id": trace.get("subjectRef"),
                "member_name": (
                    f"{member.get('firstName', '')} {member.get('lastName', '')}".strip()
                    or None
                ),
                "requested_service": self._requested_service(trace, member),
                "agent_recommendation": outcome.get("decision"),
                "agent_confidence": outcome.get("confidence"),
                "escalation_reason": (trace.get("audit") or {}).get("reviewRequiredReason"),
                "case_brief": review.get("caseBrief"),
                "escalated_at": trace.get("updatedAt"),
            })
        return {"count": len(queue), "cases": queue}

    @staticmethod
    def _requested_service(trace: dict, member: dict) -> str:
        """What was asked for.

        `trace.requested_service` is the field for it but nothing writes it yet, so
        fall back to the pending action that links to this trace.
        """
        requested = (trace.get("requested_service") or "").strip()
        if requested:
            return requested
        for action in member.get("pendingActions") or []:
            if action.get("linkedAuditTraceId") == trace.get("traceId"):
                return action.get("proposedTreatment")
        return None

    # --- the decision ---------------------------------------------------------

    def _linked_claim_id(self, member_id: str, trace_id: str) -> str:
        """The `claimId` of the claim this trace decided, if there is one.

        Only `claimId` — never `_id`. `ClaimRepository` keys on the business id, so an
        ObjectId returned from here would look like a found claim and then fail the
        update, reporting a cascade error for a claim that exists. A claim without a
        `claimId` is better treated as no linked claim.
        """
        for claim in self.claim_repo.find_by_member(member_id) or []:
            if claim.get("linkedAuditTraceId") == trace_id:
                return claim.get("claimId")
        return None

    def _open_action_id(self, member_id: str, trace_id: str) -> str:
        member = self.members.get_member(member_id) or {}
        for action in member.get("pendingActions") or []:
            if action.get("linkedAuditTraceId") == trace_id:
                return action.get("actionId")
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
        `ClaimService.update_claim_status` refuses to set a decided status unless the
        linked trace already records that decision — the claim and its trace must tell
        the same story, and doing it the other way round trips that guardrail.

        The cascade is best-effort *after* the physician's decision is recorded: a
        claim or pending-action write that fails must not unwind a completed clinical
        decision, so failures are reported in the response rather than raised.

        Raises ValueError for an invalid decision, a case not routed to a human, or one
        already closed (-> HTTP 400/404 at the route).
        """
        decision = (decision or "").strip().lower()
        if decision not in PHYSICIAN_DECISIONS:
            raise ValueError(
                f"decision must be one of {PHYSICIAN_DECISIONS}, got {decision!r}"
            )

        trace = self.traces.get_by_key(trace_id)
        if not trace:
            raise LookupError(f"Trace {trace_id} not found")

        member_id = trace.get("subjectRef")
        agent_recommendation = (trace.get("outcome") or {}).get("decision")
        # Read before closing: `close_trace` resolves nothing on the member, but the
        # claim link is easier to find while the case is still recognisably open.
        claim_id = self._linked_claim_id(member_id, trace_id)
        action_id = self._open_action_id(member_id, trace_id)

        # Bounded authority lives here: refuses a trace never routed to a human, and
        # one already closed. Also sets the override flags when the physician diverges
        # from the agent, recomputes the member summary, and notifies the member.
        closed = self.audit.close_trace(
            trace_id,
            medical_director_id=medical_director_id,
            decision=decision,
            notes=notes,
        )

        cascade = {"claim": None, "pending_action": None, "errors": []}

        if claim_id:
            try:
                self.claims.update_claim_status(
                    claim_id,
                    status=_CLAIM_STATUS[decision],
                    paid_amt=paid_amt,
                    member_owed=member_owed,
                    denial_reason=("medical_necessity" if decision == "denied" else None),
                    linked_audit_trace_id=trace_id,
                )
                cascade["claim"] = {"claim_id": claim_id, "status": _CLAIM_STATUS[decision]}
            except Exception as e:
                logger.error("claim %s not updated after review of %s: %s", claim_id, trace_id, e)
                cascade["errors"].append(f"claim {claim_id}: {e}")
        else:
            cascade["errors"].append(f"no claim links to trace {trace_id}")

        if action_id:
            try:
                self.members.update_pending_action(member_id, action_id, status="resolved")
                cascade["pending_action"] = {"action_id": action_id, "status": "resolved"}
            except Exception as e:
                logger.error("pending action %s not resolved for %s: %s", action_id, member_id, e)
                cascade["errors"].append(f"pending action {action_id}: {e}")
        else:
            cascade["errors"].append(f"no pending action links to trace {trace_id}")

        review = closed.get("review") or {}
        outcome = closed.get("outcome") or {}
        return {
            "trace_id": trace_id,
            "member_id": member_id,
            "status": closed.get("status"),
            "decision": outcome.get("decision"),
            "agent_recommendation": agent_recommendation,
            # True when the physician did not follow the agent. The single most
            # important number in this endpoint for anyone auditing the system.
            "override": bool(outcome.get("overrideFlag")),
            "override_reason": outcome.get("overrideReason"),
            "closed_by": review.get("closedBy"),
            "closed_at": review.get("closedAt"),
            "notes": review.get("notes"),
            "claim": cascade["claim"],
            "pending_action": cascade["pending_action"],
            "cascade_errors": cascade["errors"],
            "detail": (
                f"Trace {trace_id} closed {outcome.get('decision')} by "
                f"{review.get('closedBy')}"
                + (
                    f", overriding the agent's {agent_recommendation!r} recommendation."
                    if outcome.get("overrideFlag")
                    else f", concurring with the agent's {agent_recommendation!r} "
                    "recommendation."
                )
            ),
        }
