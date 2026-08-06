"""Business logic for member operations.

Reads and narrow clinical writes on the core member object. Under the official
data model the regulator-ready record is the Audit Log decision trace (see the
`audit` domain), which captures reasoning as memory-typed `steps[]`; there is no
longer a separate per-read event trail, so these operations no longer emit
incidental audit rows.
"""

from datetime import datetime, timezone

from db.mdb import get_connector
from shared.collections import Collections
from shared.summary import compute_summary_fields
from .repository import MemberRepository

# Lifecycle a pending action may move through. Enforced here rather than trusted
# from the caller: an unrecognised status would leave the frontend's "Pending
# Actions" card unable to decide what to render.
PENDING_ACTION_STATUSES = ("pending", "in_progress", "resolved")


class MemberService:
    """Service layer for member-related operations."""

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = MemberRepository(connector)
        # Traces are read directly rather than through AuditRepository: `audit`'s
        # package __init__ imports its service, which imports `members`, so a
        # domain-level import here would close a cycle. The summary derivation
        # itself lives in shared.summary, shared with that service.
        self._connector = connector

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
        return self.repository.get_by_key(member_id)

    def get_members_by_policy(self, policy_id: str) -> list:
        """Retrieve all members enrolled under a policy."""
        return self.repository.find_by_policy(policy_id)

    def list_all_members(self) -> list:
        """Retrieve all members."""
        return self.repository.find()

    def list_pending_authorizations(self) -> list:
        """Insurance Agent work queue: members with an unresolved pending action.

        Includes both `pending` (never started) and `in_progress` (a case is open,
        possibly waiting on a medical director). An escalated case must keep showing
        up here — it is not finished, and dropping it would make an awaited human
        decision invisible.
        """
        return self.repository.find_with_open_pending_actions()

    def update_pending_action(
        self,
        member_id: str,
        action_id: str,
        status: str,
        linked_audit_trace_id: str = None,
    ) -> dict:
        """Advance one `pendingActions[]` entry through its lifecycle.

        This is what drives the member-facing "Start Process" trigger and its
        resolution: `in_progress` at the very start of a case, `resolved` only once
        the case has actually closed. An escalated case stays `in_progress` with its
        trace attached, so the frontend can distinguish "awaiting medical director"
        from "not started".

        `linked_audit_trace_id` is written only when supplied, so a later
        status-only call cannot erase a trace link set earlier.

        Returns the updated entry. Raises ValueError for an unknown status
        (-> HTTP 400) or when the member or action does not exist (-> HTTP 404,
        distinguished by the caller on the message).
        """
        status = (status or "").strip().lower()
        if status not in PENDING_ACTION_STATUSES:
            raise ValueError(
                f"status must be one of {PENDING_ACTION_STATUSES}, got {status!r}"
            )

        member = self.repository.get_by_key(member_id)
        if not member:
            raise LookupError(f"Member {member_id} not found")
        actions = member.get("pendingActions") or []
        if not any(a.get("actionId") == action_id for a in actions):
            # Distinguished from a missing member: the agent can act on the
            # difference — a wrong member id is a lookup bug, a wrong action id
            # usually means the action was already resolved and replaced.
            raise LookupError(
                f"Member {member_id} has no pending action {action_id}. "
                f"Known actions: {[a.get('actionId') for a in actions] or 'none'}"
            )

        updates = {"status": status}
        if linked_audit_trace_id:
            updates["linkedAuditTraceId"] = linked_audit_trace_id
        self.repository.update_pending_action(member_id, action_id, updates)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # The record changed, but the summary projection was not recalculated —
        # only `updatedAt` moves. `summary.updated_at` belongs to
        # `recompute_summary`.
        self.repository.touch(member_id, now)

        member = self.repository.get_by_key(member_id)
        entry = next(
            a for a in (member.get("pendingActions") or []) if a.get("actionId") == action_id
        )
        return {"memberId": member_id, "pendingAction": entry, "updatedAt": now}

    def recompute_summary(self, member_id: str, last_authorization_status: str = None) -> dict:
        """Refresh `Member.summary` from the member's decision traces.

        Derived, not incremented. The tool catalog frames this as applying an
        `open_authorization_delta`, but a delta assumes exactly one writer and this
        field has two — this endpoint and the care-coordination path's
        `process_trace`. Counting the traces instead means the two can run in any
        order, or twice, and still agree. `shared.summary` holds the derivation both
        use.

        `last_authorization_status` is accepted as an override for the rare case
        where a caller knows the outcome before it has landed on a trace; when
        omitted (the normal path) it is derived too.

        Returns the updated summary, or None when the member does not exist.
        """
        member = self.repository.get_by_key(member_id)
        if not member:
            return None

        traces = list(
            self._connector.get_collection(Collections.AUDIT_LOG).find(
                {"subjectRef": member_id}
            )
        )
        fields = compute_summary_fields(traces)
        if last_authorization_status:
            fields["last_authorization_status"] = last_authorization_status
        fields["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        self.repository.set_summary(member_id, fields)
        summary = {**(member.get("summary") or {}), **fields}
        return {"memberId": member_id, "summary": summary, "traceCount": len(traces)}

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
        member = self.repository.get_by_key(member_id)
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
        member = self.repository.get_by_key(member_id)
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
