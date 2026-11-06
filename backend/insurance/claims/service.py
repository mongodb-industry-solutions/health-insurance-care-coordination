"""Business logic for claims.

Claims are *opened* by the Insurance Agent (`create_claim`, in-process in the agent). The
backend reads them for the UI and settles them when a medical director closes an escalated
case, so it needs the same status guardrail the agent applies.
"""

from collections import defaultdict
from datetime import datetime, timezone

from shared.collections import Collections
from .repository import ClaimRepository

# Statuses that assert the insurer is paying.
_PAYING_STATUSES = ("approved", "approved_restricted", "paid")

# Trace decisions that support a paying claim status.
_APPROVAL_DECISIONS = ("approved", "approved_restricted")

# The only claim status permitted while the linked trace has reached no decision.
_UNDECIDED_STATUS = "pending"

VALID_CLAIM_STATUSES = ("pending", "approved", "approved_restricted", "denied", "paid")


def _parse_ts(ts: str) -> datetime:
    """Parse a claim's adjudicated_at ISO timestamp (fill-date proxy)."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ClaimService:
    """Service layer for claims operations."""

    def __init__(self, connector):
        self.repository = ClaimRepository(connector)
        # Traces are read straight off the collection: the claim guardrail only needs the
        # trace's decision and closure, and a domain-level import of `trace` would couple
        # the two packages for one read.
        self._traces = connector.get_collection(Collections.AUDIT_LOG)

    def update_claim_status(
        self,
        claim_id: str,
        status: str,
        paid_amt: float = 0,
        member_owed: float = 0,
        denial_reason: str = None,
        linked_audit_trace_id: str = None,
    ) -> dict:
        """Apply a reached decision to its claim.

        Enforces the consistency guardrail: **a claim's status must agree with its linked
        decision trace, in both directions, and the trace must be closed.** The claim and
        the trace are two views of one determination. `pending` is always permitted: a case
        in flight, or escalated and awaiting a medical director, is legitimately undecided.

        Raises LookupError for a missing claim and ValueError for an invalid status or a
        guardrail violation.
        """
        status = (status or "").strip().lower()
        if status not in VALID_CLAIM_STATUSES:
            raise ValueError(f"status must be one of {VALID_CLAIM_STATUSES}, got {status!r}")

        claim = self.repository.get_by_key(claim_id)
        if not claim:
            raise LookupError(f"Claim {claim_id} not found")

        trace_id = linked_audit_trace_id or claim.get("linkedAuditTraceId")
        if status != _UNDECIDED_STATUS:
            if not trace_id:
                raise ValueError(
                    f"Cannot set claim {claim_id} to {status!r} with no linked decision "
                    "trace: there is nothing recording how the case was decided."
                )
            trace = self._traces.find_one({"traceId": trace_id})
            if not trace:
                raise ValueError(
                    f"Cannot set claim {claim_id} to {status!r}: linked trace "
                    f"{trace_id} does not exist, so the decision cannot be verified."
                )
            decision = ((trace.get("outcome") or {}).get("decision") or "").strip().lower()
            if not decision:
                raise ValueError(
                    f"Cannot set claim {claim_id} to {status!r}: trace {trace_id} records "
                    "no decision, so there is nothing to apply."
                )
            if not (trace.get("review") or {}).get("closedBy"):
                raise ValueError(
                    f"Cannot set claim {claim_id} to {status!r}: trace {trace_id} is not "
                    "closed, so its decision is still a recommendation."
                )
            if status in _PAYING_STATUSES and decision not in _APPROVAL_DECISIONS:
                raise ValueError(
                    f"Cannot set claim {claim_id} to {status!r} while trace {trace_id} "
                    f"records decision {decision!r}. The claim and its trace must tell the "
                    "same story."
                )
            if status == "denied" and decision != "denied":
                raise ValueError(
                    f"Cannot deny claim {claim_id} while trace {trace_id} records decision "
                    f"{decision!r}. A denial must be backed by a recorded determination."
                )

        updates = {
            "status": status,
            "paidAmt": paid_amt,
            "memberOwed": member_owed,
            "denialReason": denial_reason or None,
            "updatedAt": _now(),
            # Mirrored legacy key, kept in step with `status`.
            "outcome": status,
        }
        if trace_id:
            updates["linkedAuditTraceId"] = trace_id

        self.repository.update_fields(claim_id, updates)
        updated = self.repository.get_by_key(claim_id)
        return {k: v for k, v in (updated or {}).items() if k != "_id"}

    def get_member_claims(self, member_id: str) -> list:
        """Retrieve all claims for a member."""
        return self.repository.find_by_member(member_id)

    def detect_refill_gaps(
        self,
        member_id: str,
        drug: str = None,
        cadence_days: int = 30,
        gap_factor: float = 1.5,
    ) -> dict:
        """Find breaks in medication refill cadence.

        Deterministic interval analysis over the member's pharmacy claims (that's where the
        billing view of fill dates lives). For each drug, consecutive fills are compared; any
        interval longer than cadence_days * gap_factor is flagged as a gap. This is the
        billing view; the clinical truth is `dispense_history`, which the care agent reads.
        """
        claims = self.repository.find_by_member(member_id)
        pharmacy = [c for c in claims if str(c.get("service", "")).startswith("pharmacy - ")]
        if drug:
            pharmacy = [c for c in pharmacy if c["service"] == f"pharmacy - {drug}"]

        by_drug = defaultdict(list)
        for c in pharmacy:
            by_drug[c["service"]].append(c)

        threshold = cadence_days * gap_factor
        gaps = []
        for service, series in by_drug.items():
            series.sort(key=lambda c: c["adjudicated_at"])
            drug_name = service.replace("pharmacy - ", "")
            for prev, nxt in zip(series, series[1:]):
                interval = (_parse_ts(nxt["adjudicated_at"]) - _parse_ts(prev["adjudicated_at"])).days
                if interval > threshold:
                    gaps.append({
                        "drug": drug_name,
                        "previous_fill": prev["adjudicated_at"][:10],
                        "next_fill": nxt["adjudicated_at"][:10],
                        "gap_days": interval,
                        "approx_missed_fills": max(1, round(interval / cadence_days) - 1),
                    })

        return {
            "member_id": member_id,
            "drug": drug,
            "expected_cadence_days": cadence_days,
            "count": len(gaps),
            "gaps": gaps,
        }
