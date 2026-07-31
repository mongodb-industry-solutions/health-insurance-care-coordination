"""Business logic for claims and comparable case retrieval."""

from collections import defaultdict
from datetime import datetime

from db.mdb import get_connector
from .repository import ClaimRepository


def _parse_ts(ts: str) -> datetime:
    """Parse a claim's adjudicated_at ISO timestamp (fill-date proxy)."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


class ClaimService:
    """Service layer for claims operations.

    Provides access to adjudicated claim history and comparable case retrieval
    (episodic memory for authorization decisions).
    """

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = ClaimRepository(connector)

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
        return self.repository.get_by_id(claim_id)

    def list_all_claims(self) -> list:
        """Retrieve all claims."""
        return self.repository.find()
