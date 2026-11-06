"""Business logic for the clinical profile.

Two jobs only: read the profile (and the physician's order) for the composed views and the
opening message, and make the narrow writes the **clinical sync** needs. Those writes used to
be done by the Insurance Agent's tools straight into the combined member document; they now
cross the data boundary, so the backend, the one component allowed to hold both databases,
does them.

Every write is idempotent and a compare-and-set where it can be, so a retried turn cannot
double-apply it.
"""

from datetime import datetime, timezone
from typing import Optional

from .repository import ProfileRepository

OPEN_ACTION_STATUSES = ("pending", "in_progress")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _public(profile: Optional[dict]) -> Optional[dict]:
    if profile is None:
        return None
    return {k: v for k, v in profile.items() if k != "_id"}


class ProfileService:
    def __init__(self, connector):
        self.repository = ProfileRepository(connector)

    # --------------------------------------------------------------------------- reads

    def get_profile(self, member_id: str) -> Optional[dict]:
        return _public(self.repository.get_by_key(member_id))

    def get_action(self, member_id: str, action_id: str = None) -> Optional[dict]:
        """One of the member's pending actions: the named one, or the one still open.

        An `in_progress` action outranks a `pending` one (a case already opened is the one
        to work); with several open the first is returned and the caller can see the rest
        via `open_actions`.
        """
        profile = self.repository.get_by_key(member_id)
        if not profile:
            return None
        actions = profile.get("pendingActions") or []
        if action_id:
            return next((a for a in actions if a.get("actionId") == action_id), None)
        open_actions = [a for a in actions if (a.get("status") or "") in OPEN_ACTION_STATUSES]
        open_actions.sort(key=lambda a: 0 if a.get("status") == "in_progress" else 1)
        return open_actions[0] if open_actions else None

    def open_actions(self, member_id: str) -> list:
        profile = self.repository.get_by_key(member_id) or {}
        return [
            a for a in profile.get("pendingActions") or []
            if (a.get("status") or "") in OPEN_ACTION_STATUSES
        ]

    @staticmethod
    def diagnosis_display(profile: dict, code: str) -> Optional[str]:
        """The display name of a diagnosis code on the profile, for the opening message."""
        wanted = (code or "").strip().upper()
        for d in (profile.get("clinical_history") or {}).get("diagnoses") or []:
            if (d.get("code") or "").strip().upper() == wanted:
                return d.get("display")
        return None

    # --------------------------------------------------------------- the clinical sync

    def start_action(self, member_id: str, action_id: str) -> bool:
        """`pending` -> `in_progress`. True if this call moved it (a compare-and-set, so a
        second click cannot also win)."""
        moved = self.repository.set_action_fields(
            member_id, action_id, {"status": "in_progress"}, only_if={"status": "pending"}
        )
        if moved:
            self.repository.touch(member_id, _now())
        return bool(moved)

    def link_trace(self, member_id: str, action_id: str, trace_id: str) -> bool:
        """Attach the trace id to the action. Idempotent."""
        action = self.get_action(member_id, action_id)
        if action is None or action.get("linkedAuditTraceId") == trace_id:
            return False
        moved = self.repository.set_action_fields(
            member_id, action_id, {"linkedAuditTraceId": trace_id}
        )
        if moved:
            self.repository.touch(member_id, _now())
        return bool(moved)

    def resolve_action(self, member_id: str, action_id: str) -> bool:
        """Mark the action `resolved`. Idempotent; never un-resolves."""
        moved = self.repository.set_action_fields(
            member_id, action_id, {"status": "resolved"}, only_if={"status": "in_progress"}
        )
        if moved:
            self.repository.touch(member_id, _now())
        return bool(moved)

    def rollback_start(self, member_id: str, action_id: str) -> bool:
        """`in_progress` -> `pending`, only while no trace was ever linked. Undoes
        `start_action` when the agent failed before it opened a case, so the member can
        press Start again."""
        moved = self.repository.set_action_fields(
            member_id, action_id, {"status": "pending"},
            only_if={"status": "in_progress", "linkedAuditTraceId": None},
        )
        if moved:
            self.repository.touch(member_id, _now())
        return bool(moved)

    def mark_approved_therapy(self, member_id: str, therapy: str) -> bool:
        """Record the approved therapy on the care plan and clear `considering_therapy`.
        Idempotent. Declines to write an empty therapy rather than blanking the plan."""
        therapy = (therapy or "").strip()
        if not therapy:
            return False
        profile = self.repository.get_by_key(member_id)
        if not profile:
            return False
        plan = profile.get("current_care_plan") or {}
        if plan.get("approved_therapy") == therapy and not plan.get("considering_therapy"):
            return False
        return bool(
            self.repository.set_care_plan_fields(
                member_id, {"approved_therapy": therapy, "considering_therapy": None}, _now()
            )
        )
