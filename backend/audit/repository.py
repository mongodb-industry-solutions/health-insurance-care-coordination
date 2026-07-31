from core.repository import Repository
from shared.collections import Collections


class AuditRepository(Repository):
    """Access to the `audit_log` collection — the regulator-ready decision-trace store.

    Each prior-authorization decision is one trace document (decisionType
    PRIOR_AUTHORIZATION) whose `steps[]` capture the memory-typed reasoning. This
    collection replaced the former standalone `authorizations` collection, so the
    file -> process -> close lifecycle queries live here.
    """

    collection_name = Collections.AUDIT_LOG

    def find_by_subject(self, subject_ref):
        """All traces for a subject (member id), chronological."""
        return list(
            self.collection.find({"subjectRef": subject_ref}).sort("createdAt", 1)
        )

    # Backwards-friendly alias: a member's traces == traces whose subject is the member.
    def find_by_member(self, member_id):
        return self.find_by_subject(member_id)

    def find_pending_by_member(self, member_id):
        """The member's most recently filed, not-yet-decided prior-auth trace."""
        pending = self.find({"subjectRef": member_id, "status": "pending"})
        return max(pending, key=lambda t: t.get("createdAt", ""), default=None)

    def find_routed_to_human(self):
        """Open traces awaiting a medical director (routed and not yet closed)."""
        return self.find({"review.routedToHuman": True, "review.closedBy": None})

    def delete_by_member(self, member_id):
        """Remove all traces for a subject.

        Append-only is the runtime contract; this delete exists ONLY for the
        out-of-band demo reset, never for workflow code.
        """
        return self.delete_by({"subjectRef": member_id})
