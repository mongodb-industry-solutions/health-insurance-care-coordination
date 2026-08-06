"""Business logic for claims and comparable case retrieval."""

import random
from collections import defaultdict
from datetime import date, datetime, timezone

from pymongo.errors import DuplicateKeyError

from db.mdb import get_connector
from shared.collections import Collections
from members.repository import MemberRepository
from .repository import ClaimRepository

# Statuses that assert the insurer is paying. None may be set while the linked
# decision trace says otherwise — see `update_claim_status`.
_PAYING_STATUSES = ("approved", "approved_restricted", "paid")

# Trace outcomes that contradict a paying claim status.
_NON_PAYING_DECISIONS = ("denied", "pending", None, "")

VALID_CLAIM_STATUSES = (
    "pending",
    "approved",
    "approved_restricted",
    "denied",
    "paid",
)

# How many times to re-draw a colliding claimId before giving up. Five digits is
# 90,000 values per state-year, so two collisions in a row already means something
# is wrong with the generator rather than with luck.
_ID_ATTEMPTS = 8


def _parse_ts(ts: str) -> datetime:
    """Parse a claim's adjudicated_at ISO timestamp (fill-date proxy)."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ClaimService:
    """Service layer for claims operations.

    Provides access to adjudicated claim history and comparable case retrieval
    (episodic memory for authorization decisions).
    """

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = ClaimRepository(connector)
        self.member_repo = MemberRepository(connector)
        # Traces are read straight off the collection rather than through
        # AuditRepository: `audit`'s package __init__ imports its service, which
        # imports this module, so a domain-level import here would close a cycle.
        self._connector = connector

    # --- claim creation ------------------------------------------------------

    def _mint_claim_id(self, state: str, service_date: str) -> str:
        """Generate an unused `claimId` shaped like the existing data.

        `CLM-{STATE}-{YEAR}-{5 digits}` — e.g. `CLM-IL-2026-84027` — matching the
        seeded claims rather than the `TRC-{uuid}` style used for traces, so one
        collection does not end up with two visibly different id formats.

        Randomly drawn rather than sequential: a max-scan-and-increment is racy
        between two concurrent creates, and a counters collection would be an
        addition to a data model that is meant to be final. The trade is that ids
        are not consecutive. Uniqueness rests on the unique index on `claimId`;
        this loop just avoids provoking it, and `create_claim` still catches
        `DuplicateKeyError` for the race this cannot close.
        """
        prefix = f"CLM-{(state or 'XX').strip().upper()[:2]}-{service_date[:4]}"
        for _ in range(_ID_ATTEMPTS):
            candidate = f"{prefix}-{random.randint(10000, 99999)}"
            if not self.repository.exists(candidate):
                return candidate
        raise ValueError(
            f"Could not generate an unused claimId for {prefix} after "
            f"{_ID_ATTEMPTS} attempts."
        )

    def create_claim(
        self,
        member_id: str,
        procedure_code: str,
        procedure_desc: str,
        diagnosis_code: str,
        diagnosis_display: str,
        billed_amt: float,
        claim_type: str = "specialty_pharmacy",
        service_date: str = None,
    ) -> dict:
        """Insurance Agent, step 0: open a claim in `pending` status.

        `policyId` and the embedded `provider` are read off the member record rather
        than accepted from the caller, so the claim cannot disagree with the record
        it was raised from — an agent that mis-remembers a provider should not be
        able to write that into the financial record.

        Nothing is decided here. The claim opens `pending`, with zero paid, zero
        owed, and no linked trace; step 9 fills those in.

        Raises LookupError when the member does not exist (-> HTTP 404) and
        ValueError when the record lacks a managing provider (-> HTTP 400).
        """
        member = self.member_repo.get_by_key(member_id)
        if not member:
            raise LookupError(f"Member {member_id} not found")

        provider = ((member.get("current_care_plan") or {}).get("managing_provider")) or {}
        if not provider.get("providerId"):
            raise ValueError(
                f"Member {member_id} has no managing provider on the current care plan, "
                "so there is no treating provider to file the claim against."
            )

        as_of = (service_date or date.today().isoformat())[:10]
        now = _now()
        status = "pending"
        claim = {
            "claimId": self._mint_claim_id(member.get("state"), as_of),
            "memberId": member["memberId"],
            "policyId": member.get("policyId"),
            "provider": {
                "providerId": provider.get("providerId"),
                "name": provider.get("name"),
                "specialty": provider.get("specialty"),
            },
            "procedureCode": (procedure_code or "").strip().upper(),
            "procedureDesc": procedure_desc,
            "diagnosisCode": (diagnosis_code or "").strip().upper(),
            "diagnosisDisplay": diagnosis_display,
            "serviceDate": as_of,
            "claimType": claim_type,
            "billedAmt": billed_amt,
            "paidAmt": 0,
            "memberOwed": 0,
            "currency": "USD",
            "status": status,
            "denialReason": None,
            "linkedAuditTraceId": None,
            # Legacy retrieval keys, mirrored from the coded fields. The final data
            # model dropped them, but `find_comparable` matches on them, so a claim
            # written without them would be invisible to episodic retrieval — a new
            # claim would never become precedent for anyone.
            "service": procedure_desc,
            "diagnosis": (diagnosis_code or "").strip().upper(),
            "outcome": status,
            "createdAt": now,
            "updatedAt": now,
        }

        try:
            self.repository.insert_claim(claim)
        except DuplicateKeyError:
            # The unique index caught a race the pre-check could not. One retry with
            # a fresh draw; a second failure is not luck and should surface.
            claim["claimId"] = self._mint_claim_id(member.get("state"), as_of)
            self.repository.insert_claim(claim)

        return {k: v for k, v in claim.items() if k != "_id"}

    def update_claim_status(
        self,
        claim_id: str,
        status: str,
        paid_amt: float = 0,
        member_owed: float = 0,
        denial_reason: str = None,
        linked_audit_trace_id: str = None,
    ) -> dict:
        """Insurance Agent, step 9: apply a reached decision to its claim.

        Enforces the consistency guardrail from the data model: a claim may not
        assert that the insurer is paying while its linked decision trace records a
        denial or is still undecided. The claim and the trace are two views of one
        determination, and a demo that lets them disagree has no audit trail worth
        inspecting.

        Raises LookupError for a missing claim (-> HTTP 404) and ValueError for an
        invalid status or a guardrail violation (-> HTTP 400).
        """
        status = (status or "").strip().lower()
        if status not in VALID_CLAIM_STATUSES:
            raise ValueError(
                f"status must be one of {VALID_CLAIM_STATUSES}, got {status!r}"
            )

        claim = self.repository.get_by_key(claim_id)
        if not claim:
            raise LookupError(f"Claim {claim_id} not found")

        trace_id = linked_audit_trace_id or claim.get("linkedAuditTraceId")
        if status in _PAYING_STATUSES:
            if not trace_id:
                raise ValueError(
                    f"Cannot set claim {claim_id} to {status!r} with no linked decision "
                    "trace: there is nothing recording that the payment was authorized."
                )
            trace = self._connector.get_collection(Collections.AUDIT_LOG).find_one(
                {"traceId": trace_id}
            )
            if not trace:
                raise ValueError(
                    f"Cannot set claim {claim_id} to {status!r}: linked trace "
                    f"{trace_id} does not exist, so the decision cannot be verified."
                )
            decision = (trace.get("outcome") or {}).get("decision")
            if decision in _NON_PAYING_DECISIONS:
                raise ValueError(
                    f"Cannot set claim {claim_id} to {status!r} while trace {trace_id} "
                    f"records decision {decision!r}. Resolve the trace first — the claim "
                    "and its trace must tell the same story."
                )

        now = _now()
        updates = {
            "status": status,
            "paidAmt": paid_amt,
            "memberOwed": member_owed,
            "denialReason": denial_reason or None,
            "updatedAt": now,
            # Keep the mirrored legacy key in step with `status`, so a claim that
            # becomes an approval also becomes discoverable as precedent.
            "outcome": status,
        }
        if trace_id:
            updates["linkedAuditTraceId"] = trace_id

        self.repository.update_fields(claim_id, updates)
        updated = self.repository.get_by_key(claim_id)
        return {k: v for k, v in (updated or {}).items() if k != "_id"}

    def find_comparable_cases(
        self, service: str, diagnosis: str, member_id: str = None
    ) -> list:
        """Find comparable precedent (episodic memory) — other members' approved
        claims for the same service + diagnosis. Phase 1, step 6.

        The querying member is excluded (passed as `member_id`).

        NOTE (enhancement): matching is exact on service + diagnosis. Replace with
        Atlas Vector Search over `presentation_profile` embeddings to retrieve by
        semantic similarity rather than exact codes/strings — the infra is already
        scaffolded (vogayeai/, _vector_search_idx_creator.py).
        """
        return self.repository.find_comparable(
            service, diagnosis, exclude_member=member_id
        )

    def get_member_claims(self, member_id: str) -> list:
        """Retrieve all adjudicated claims for a member."""
        return self.repository.find_by_member(member_id)

    def detect_refill_gaps(
        self,
        member_id: str,
        drug: str = None,
        cadence_days: int = 30,
        gap_factor: float = 1.5,
    ) -> dict:
        """Phase 2, step 1: find breaks in medication refill cadence.

        Deterministic interval analysis over the member's pharmacy claims (that's
        where fill dates live — not medications/treatment_responses). For each drug,
        consecutive fills are compared; any interval longer than
        cadence_days * gap_factor is flagged as a gap. Generalized: catches any
        gap for any drug, not a hardcoded 10-day window.
        """
        claims = self.repository.find_by_member(member_id)
        pharmacy = [c for c in claims if str(c.get("service", "")).startswith("pharmacy - ")]
        if drug:
            pharmacy = [c for c in pharmacy if c["service"] == f"pharmacy - {drug}"]

        # Group by drug (service) and analyze each fill series independently.
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

    def get_claim(self, claim_id: str) -> dict:
        """Retrieve a specific claim."""
        return self.repository.get_by_key(claim_id)

    def list_all_claims(self) -> list:
        """Retrieve all claims."""
        return self.repository.find()
