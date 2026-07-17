"""Business logic for member operations."""

from datetime import datetime, timezone

from db.mdb import get_connector
from audit.repository import AuditRepository
from .repository import MemberRepository


class MemberService:
    """Service layer for member-related operations."""

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = MemberRepository(connector)
        # Audit is a cross-cutting record of what happened, not another domain's
        # business data — so a write that must be audited logs it here directly.
        self.audit = AuditRepository(connector)

    def get_clinical_context(self, member_id: str, agent: str = None) -> dict:
        """Retrieve member's clinical history and eligibility for decision-making.

        Phase 1, step 3. When an `agent` is supplied, the read is an auditable PHI
        access and logs a `read clinical context` entry server-side (step 3a) — so
        the trail can't have gaps that depend on the caller remembering to log.
        """
        doc = self.repository.get_clinical_history(member_id)
        if not doc:
            return None

        if agent:
            self.audit.record(
                member_id=member_id,
                agent=agent,
                action="read clinical context",
                fields_accessed=[
                    "clinical_history",
                    "eligibility",
                    "current_care_plan",
                ],
            )

        return {
            "member_id": member_id,
            "clinical_history": doc.get("clinical_history"),
            "eligibility": doc.get("eligibility"),
            "current_care_plan": doc.get("current_care_plan"),
        }

    def get_member(self, member_id: str) -> dict:
        """Retrieve complete member document."""
        return self.repository.get_by_id(member_id)

    def get_members_by_plan(self, plan_id: str) -> list:
        """Retrieve all members enrolled in a plan."""
        return self.repository.find_by_plan(plan_id)

    def list_all_members(self) -> list:
        """Retrieve all members."""
        return self.repository.find()

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

        A single clinical documentation event (via EHR integration) that:
          - appends a treatment_response assessment (e.g. 'inadequate'),
          - marks the first-line drug discontinued with that reason,
          - records the therapy now being considered,
          - bumps updated_at,
        then logs the step-2a audit entry. Returns the updated member, or None if
        the member does not exist.
        """
        member = self.repository.get_by_id(member_id)
        if not member:
            return None

        now = datetime.now(timezone.utc)
        provider = member.get("current_care_plan", {}).get("managing_provider", "unknown")

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

        member["updated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.repository.upsert(member)

        self.audit.record(
            member_id=member_id,
            agent="ehr_integration",
            action="treatment response documented",
            fields_accessed=[
                "clinical_history.treatment_responses",
                "clinical_history.medications",
                "current_care_plan.considering_therapy",
            ],
        )
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

        After reasoning that a detected refill gap is explained (e.g. a documented
        medication hold, not a discontinuation), the verification agent records that
        conclusion as a treatment_response so the effective trial stands and the
        case proceeds. Logs the step-2b audit (`resolve refill gap`), citing the
        clinical note that explained the gap via `related_note`.

        The conclusion text is authored by the agent; this method only persists and
        audits it. Generic — no condition/drug is hardcoded. Returns the updated
        member, or None if the member does not exist.
        """
        member = self.repository.get_by_id(member_id)
        if not member:
            return None

        now = datetime.now(timezone.utc)
        clinical = member.setdefault("clinical_history", {})
        clinical.setdefault("treatment_responses", []).append({
            "drug": drug,
            "duration_months": effective_trial_months,
            "outcome": "gap_reviewed",
            "notes": conclusion,
            "documented_by": "verification_agent",
            "documented_on": now.strftime("%Y-%m-%d"),
        })
        member["updated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.repository.upsert(member)

        self.audit.record(
            member_id=member_id,
            agent="verification_agent",
            action="resolve refill gap",
            fields_accessed=["clinical_history.treatment_responses"],
            related_note=related_note,
        )
        return member
