"""Business logic for member operations.

Reads and narrow clinical writes on the core member object. Under the official
data model the regulator-ready record is the Audit Log decision trace (see the
`audit` domain), which captures reasoning as memory-typed `steps[]`; there is no
longer a separate per-read event trail, so these operations no longer emit
incidental audit rows.
"""

from datetime import datetime, timezone

from db.mdb import get_connector
from .repository import MemberRepository


class MemberService:
    """Service layer for member-related operations."""

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = MemberRepository(connector)

    def get_clinical_context(self, member_id: str) -> dict:
        """Retrieve member's clinical history and eligibility for decision-making
        (Phase 1, step 3)."""
        doc = self.repository.get_clinical_history(member_id)
        if not doc:
            return None
        return {
            "member_id": member_id,
            "clinical_history": doc.get("clinical_history"),
            "eligibility": doc.get("eligibility"),
            "current_care_plan": doc.get("current_care_plan"),
        }

    def get_member(self, member_id: str) -> dict:
        """Retrieve complete member document."""
        return self.repository.get_by_id(member_id)

    def get_members_by_policy(self, policy_id: str) -> list:
        """Retrieve all members enrolled under a policy."""
        return self.repository.find_by_policy(policy_id)

    def list_all_members(self) -> list:
        """Retrieve all members."""
        return self.repository.find()

    def _provider_name(self, member: dict) -> str:
        provider = member.get("current_care_plan", {}).get("managing_provider")
        if isinstance(provider, dict):
            return provider.get("name", "unknown")
        return provider or "unknown"

    def document_treatment_response(
        self,
        member_id: str,
        drug: str,
        duration_months: int,
        outcome: str,
        notes: str,
        considering_therapy: str,
    ) -> dict:
        """Phase 1, step 1: Dr. Patel documents the treatment response.

        Appends a treatment_response assessment, marks the first-line drug
        discontinued with that reason, records the therapy now being considered,
        and bumps updatedAt. Returns the updated member, or None if it does not
        exist.
        """
        member = self.repository.get_by_id(member_id)
        if not member:
            return None

        now = datetime.now(timezone.utc)
        provider = self._provider_name(member)

        clinical = member.setdefault("clinical_history", {})

        # Append the assessment (keeps the trajectory: earlier 'ongoing' -> this one).
        clinical.setdefault("treatment_responses", []).append({
            "drug": drug,
            "duration_months": duration_months,
            "outcome": outcome,
            "notes": notes,
            "documented_by": provider,
            "documented_on": now.strftime("%Y-%m-%d"),
        })

        # Discontinue the matching medication with the documented reason.
        for med in clinical.get("medications", []):
            if med.get("display") == drug:
                med["status"] = "discontinued"
                med["reason"] = f"{outcome} response"

        # Record the therapy now under consideration.
        member.setdefault("current_care_plan", {})["considering_therapy"] = considering_therapy

        member["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.repository.upsert(member)
        return member

    def resolve_refill_gap(
        self,
        member_id: str,
        drug: str,
        effective_trial_months: int,
        conclusion: str,
        related_note: str = None,
    ) -> dict:
        """Phase 2, step 2: the verification agent attaches its gap conclusion.

        Records the agent-authored `conclusion` as a treatment_response so the
        effective trial stands and the case proceeds. Generic — no condition/drug
        is hardcoded. Returns the updated member, or None if it does not exist.
        """
        member = self.repository.get_by_id(member_id)
        if not member:
            return None

        now = datetime.now(timezone.utc)
        clinical = member.setdefault("clinical_history", {})
        entry = {
            "drug": drug,
            "duration_months": effective_trial_months,
            "outcome": "gap_reviewed",
            "notes": conclusion,
            "documented_by": "verification_agent",
            "documented_on": now.strftime("%Y-%m-%d"),
        }
        # Provenance: cite the clinical note that explained the gap so the
        # conclusion can be traced back to its source documentation (the audit
        # trail no longer carries this — it lives on the record).
        if related_note:
            entry["related_note"] = related_note
        clinical.setdefault("treatment_responses", []).append(entry)
        member["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.repository.upsert(member)
        return member
