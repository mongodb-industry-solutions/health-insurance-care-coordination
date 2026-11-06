"""Business logic for the shared authorization trace, from the backend's side.

The agents own every transition up to ESCALATED, and they make them in-process against the
same collection. The backend's part is narrow: read traces, and let a medical director close
an escalated one. Nothing here imports from `insurance/` or `clinical/`; the cascades a
closure triggers (claim, member summary, clinical sync) are orchestrated by `workflow/`.

`views/` joins each step's text on by `detailRef`; this module returns the raw envelope.
"""

from datetime import datetime, timezone

from .repository import TraceRepository
from .stages import (
    ACTOR_DIRECTOR,
    ACTOR_NONE,
    APPROVAL_DECISIONS,
    STAGE_CLOSED,
    STAGE_ESCALATED,
)

PHYSICIAN_DECISIONS = ("approved", "denied")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _without_id(trace):
    return {k: v for k, v in trace.items() if k != "_id"} if trace else trace


class TraceService:
    def __init__(self, connector):
        self.repository = TraceRepository(connector)

    # ------------------------------------------------------------------------- reads

    def get_trace(self, trace_id: str):
        return _without_id(self.repository.get_by_key(trace_id))

    def get_member_traces(self, member_id: str) -> list:
        return [_without_id(t) for t in self.repository.find_by_subject(member_id)]

    def pending_human_review(self) -> list:
        """Cases waiting on a medical director, oldest first. Derived from the trace itself
        (`review.routedToHuman` set, `review.closedBy` still null), so it cannot drift."""
        traces = [_without_id(t) for t in self.repository.find_routed_to_human()]
        traces.sort(key=lambda t: t.get("updatedAt") or t.get("createdAt") or "")
        return traces

    # ------------------------------------------------------------------------ writes

    @staticmethod
    def effective_decision(trace: dict, decision: str) -> str:
        """The decision as recorded. A physician approving a case whose plan covers the
        treatment only in part approves it *as restricted*: the restriction follows from
        the benefit design the Insurance Agent recorded in `administrativeGates`, not from
        the physician's judgement."""
        gates = trace.get("administrativeGates") or {}
        if decision == "approved" and gates.get("coverageRestriction") == "partial":
            return "approved_restricted"
        return decision

    def close_by_director(
        self, trace_id: str, medical_director_id: str, decision: str, notes: str = None
    ) -> dict:
        """ESCALATED -> CLOSED: a medical director sets the final decision.

        Bounded authority lives here: only a trace the Insurance Agent escalated can be
        human-closed, and only once. The transition is a compare-and-set on the stage, so a
        concurrent close loses rather than overwriting. If the physician diverges from the
        agent's recommendation, the override is recorded with their notes as the rationale.
        An `approved` against a partial-coverage case is recorded as `approved_restricted`.

        Raises LookupError for a missing trace and ValueError for an invalid decision, a
        case not escalated, or one already closed.
        """
        decision = (decision or "").strip().lower()
        if decision not in PHYSICIAN_DECISIONS:
            raise ValueError(f"decision must be one of {PHYSICIAN_DECISIONS}, got {decision!r}")
        if not (medical_director_id or "").strip():
            raise ValueError("medical_director_id is required.")

        trace = self.repository.get_by_key(trace_id)
        if not trace:
            raise LookupError(f"Trace {trace_id} not found")

        review = trace.get("review") or {}
        if review.get("closedBy"):
            raise ValueError(f"Trace already closed by {review['closedBy']}")
        workflow = trace.get("workflow") or {}
        if (
            not review.get("routedToHuman")
            or workflow.get("stage") != STAGE_ESCALATED
            or workflow.get("nextActor") != ACTOR_DIRECTOR
        ):
            raise ValueError(
                f"Trace {trace_id} is at stage {workflow.get('stage')} (next actor: "
                f"{workflow.get('nextActor')}); only an escalated case can be closed by a "
                "medical director. Nothing to close."
            )

        recorded = self.effective_decision(trace, decision)
        outcome = dict(trace.get("outcome") or {})
        recommended = outcome.get("decision")
        # "Approved" and "approved_restricted" are the same call; only a change of
        # direction is an override.
        as_family = lambda d: "approved" if d in APPROVAL_DECISIONS else d  # noqa: E731
        diverged = bool(recommended) and as_family(recommended) != as_family(decision)

        now = _now()
        fields = {
            "status": recorded,
            "outcome.decision": recorded,
            "review.closedBy": medical_director_id,
            "review.closedAt": now,
            "workflow.stage": STAGE_CLOSED,
            "workflow.nextActor": ACTOR_NONE,
            "updatedAt": now,
        }
        if notes:
            fields["review.notes"] = notes
        if diverged:
            fields["outcome.overrideFlag"] = True
            fields["outcome.overrideBy"] = medical_director_id
            fields["outcome.overrideReason"] = notes

        history_entry = {"stage": STAGE_CLOSED, "actor": medical_director_id, "at": now}
        if not self.repository.close_escalated(trace_id, fields, history_entry):
            raise ValueError(f"Trace {trace_id} moved on before it could be closed; read it again.")
        return self.get_trace(trace_id)
