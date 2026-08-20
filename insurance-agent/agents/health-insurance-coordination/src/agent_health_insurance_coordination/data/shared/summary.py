"""Derivation of a member's rolling `summary` fields from their decision traces.

`Member.summary` is a denormalized projection, not a source of truth: it exists so
the *next* request for a member starts from an already-informed record rather than
recounting. Anything denormalized needs exactly one writer, or the copies drift —
so both writers of these fields (the Insurance Agent's
`POST /api/members/{id}/summary` and the care-coordination path's
`AuditService._recompute_summary`) derive them here, from the traces, instead of
each applying its own increments.

This module deliberately imports nothing from the domain packages. `audit` and
`members` both import it, and `audit/__init__` already imports `members`, so a
domain import here would close an import cycle.
"""

# A trace whose closure is still outstanding counts as an open authorization.
_OPEN_DECISIONS = ("pending", None, "")


def _trace_sort_key(trace: dict) -> str:
    """Order traces oldest-first. Falls back to `createdAt` when `updatedAt` is
    absent, and to the empty string when both are, so a malformed trace sorts
    first rather than raising."""
    return trace.get("updatedAt") or trace.get("createdAt") or ""


def is_open(trace: dict) -> bool:
    """Is this decision still awaiting closure?

    A trace is open while nobody has closed it — which covers both an escalated
    case waiting on a medical director and one the agent has not finished yet.
    `review.closedBy` is the authority on this: the final data model has no
    top-level `status` field, and bounded authority is expressed precisely by
    leaving `closedBy` null until whoever owns the closure sets it.
    """
    review = trace.get("review") or {}
    if review.get("closedBy"):
        return False
    outcome = trace.get("outcome") or {}
    if outcome.get("decision") in _OPEN_DECISIONS:
        return True
    # Decided but unclosed — an escalated recommendation awaiting a human.
    return True


def status_of(trace: dict) -> str:
    """The reportable status of one trace.

    Distinguishes "escalated, awaiting a human" from the recommendation itself,
    because a member whose case is with a medical director has not been denied —
    reporting the recommendation as though it were the outcome would tell them
    the wrong thing.

    Reads `outcome.decision` and `review.*`, with a fallback to the legacy
    top-level `status` that seeded traces still carry and that the final data
    model does not define.
    """
    review = trace.get("review") or {}
    outcome = trace.get("outcome") or {}
    decision = outcome.get("decision")

    if review.get("routedToHuman") and not review.get("closedBy"):
        return "pending_review"
    if decision:
        return decision
    return trace.get("status") or "pending"


def compute_summary_fields(traces: list) -> dict:
    """Derive `open_authorization_count` and `last_authorization_status`.

    Returns `"none"` for a member who has never been through the process, which is
    what the data model specifies — distinct from `"pending"`, which would imply a
    case is in flight.

    `active_condition_count` is deliberately not touched: it is derived from the
    clinical record, not from decisions, and is not this function's business.
    """
    ordered = sorted(traces or [], key=_trace_sort_key)
    return {
        "open_authorization_count": sum(1 for t in ordered if is_open(t)),
        "last_authorization_status": status_of(ordered[-1]) if ordered else "none",
    }
