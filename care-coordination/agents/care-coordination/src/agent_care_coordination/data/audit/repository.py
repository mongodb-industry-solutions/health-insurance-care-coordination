from ..core.repository import Repository
from ..shared.collections import Collections


class AuditRepository(Repository):
    """Access to the `audit_log` collection — the regulator-ready decision-trace store.

    Each prior-authorization decision is one trace document (decisionType
    PRIOR_AUTHORIZATION) whose `steps[]` capture the memory-typed reasoning. This
    collection replaced the former standalone `authorizations` collection, so the
    file -> process -> close lifecycle queries live here.
    """

    collection_name = Collections.AUDIT_LOG
    business_key = "traceId"

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

    def find_all_sorted(self):
        """Every trace in the system, newest first.

        The compliance-wide view. Newest-first because the operational question is
        almost always "what happened recently", unlike `find_by_subject`, which is
        chronological because a single subject's traces tell a story in order.
        """
        return list(self.collection.find({}).sort("createdAt", -1))

    def exists(self, trace_id):
        """Is this business key already taken? Pre-check before minting a traceId."""
        return self.collection.count_documents({"traceId": trace_id}, limit=1) > 0

    def insert_trace(self, document):
        """Insert a new trace, letting MongoDB assign `_id`.

        Plain `insert` rather than the inherited `upsert`, which keys on a
        caller-supplied `_id` the final data model no longer defines. Raises
        `DuplicateKeyError` on a `traceId` collision.
        """
        return self.insert(document)

    def update_fields(self, trace_id, updates):
        """Write specific fields on a trace, dot-paths included.

        Field-level `$set` rather than a whole-document replace: a closure must not
        be able to roll back reasoning steps appended between the read and the write.
        Returns the number of documents modified; 0 means no trace matched.
        """
        return self.collection.update_one(
            {"traceId": trace_id}, {"$set": updates}
        ).modified_count

    def push_step(self, trace_id, step, updates=None):
        """Append one reasoning step to `steps[]`.

        `$push` rather than read-modify-write, so two steps appended concurrently
        cannot overwrite each other — with a whole-document replace, the second
        write would silently drop the first step.
        """
        update = {"$push": {"steps": step}}
        if updates:
            update["$set"] = updates
        return self.collection.update_one({"traceId": trace_id}, update).modified_count

    def delete_by_member(self, member_id):
        """Remove all traces for a subject.

        Append-only is the runtime contract; this delete exists ONLY for the
        out-of-band demo reset, never for workflow code.
        """
        return self.delete_by({"subjectRef": member_id})
