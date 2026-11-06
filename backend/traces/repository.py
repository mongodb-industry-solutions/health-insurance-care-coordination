from core.repository import Repository
from shared.collections import Collections

from .stages import ACTOR_DIRECTOR, STAGE_ESCALATED


class TraceRepository(Repository):
    """Access to the `audit_log` collection: the shared authorization trace.

    The agents write this collection in-process, one stage at a time. The backend reads it
    and makes exactly one write: a medical director closing an escalated case.
    """

    collection_name = Collections.AUDIT_LOG
    business_key = "traceId"

    def find_by_subject(self, subject_ref):
        """All traces for a subject (member id), chronological."""
        return list(self.collection.find({"subjectRef": subject_ref}).sort("createdAt", 1))

    def find_routed_to_human(self):
        """Traces a medical director owes a decision on: escalated and not yet closed."""
        return self.find({"review.routedToHuman": True, "review.closedBy": None})

    def close_escalated(self, trace_id, fields, history_entry) -> int:
        """Apply `fields` and log the transition, but only from ESCALATED with the medical
        director as next actor. A compare-and-set, so two directors (or a director and a
        retry) cannot both close the case. Returns the modified count; 0 means it had
        already moved."""
        return self.collection.update_one(
            {
                "traceId": trace_id,
                "workflow.stage": STAGE_ESCALATED,
                "workflow.nextActor": ACTOR_DIRECTOR,
                "review.closedBy": None,
            },
            {"$set": fields, "$push": {"workflow.history": history_entry}},
        ).modified_count

    def delete_by_member(self, member_id):
        """Remove all traces for a subject. Append-only is the runtime contract; this
        exists ONLY for the out-of-band demo reset, never for workflow code."""
        return self.delete_by({"subjectRef": member_id})
