"""Business logic for the insurance side of a member."""

from datetime import datetime, timezone

from shared.collections import Collections
from shared.summary import compute_summary_fields
from .repository import MemberRepository


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MemberService:
    """Service layer for insurance-side member operations."""

    def __init__(self, connector):
        self.repository = MemberRepository(connector)
        # Traces are read directly: the summary is derived from them, and this keeps
        # `insurance` from importing `trace`.
        self._traces = connector.get_collection(Collections.AUDIT_LOG)

    def get_member(self, member_id: str) -> dict:
        """Retrieve the insurance member document."""
        return self.repository.get_by_key(member_id)

    def recompute_summary(self, member_id: str, last_authorization_status: str = None):
        """Refresh `summary` from the member's decision traces.

        Derived, not incremented: the agent's closure paths and the director's decision both
        write these fields, and counting the traces means they can run in any order, or
        twice, and still agree. A field-level `$set` of the two summary fields and
        `updated_at` only. Returns None when the member does not exist.
        """
        member = self.repository.get_by_key(member_id)
        if not member:
            return None

        traces = list(self._traces.find({"subjectRef": member_id}))
        fields = compute_summary_fields(traces)
        if last_authorization_status:
            fields["last_authorization_status"] = last_authorization_status
        now = _now()
        fields["updated_at"] = now
        self.repository.set_summary(member_id, fields, now)
        return {
            "memberId": member_id,
            "summary": {**(member.get("summary") or {}), **fields},
            "traceCount": len(traces),
        }
