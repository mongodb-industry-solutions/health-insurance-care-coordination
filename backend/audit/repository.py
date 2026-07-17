import uuid
from datetime import datetime, timezone

from core.repository import Repository
from shared.collections import Collections


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AuditRepository(Repository):
    """Access to the append-only `audit_log` collection.

    Every agent interaction with a member record lands here so a regulator can
    reconstruct what was accessed, by which agent, and why.
    """

    collection_name = Collections.AUDIT_LOG

    def record(self, member_id, agent, action, fields_accessed=None,
               related_authorization=None, related_note=None, related_medication=None,
               related_guideline=None):
        # String _id and ISO-string timestamp so entries match AuditLogEntry and
        # serialize cleanly over the API. ISO timestamps also sort chronologically.
        entry = {
            "_id": f"AUD-{uuid.uuid4().hex[:12]}",
            "member_id": member_id,
            "agent": agent,
            "action": action,
            "fields_accessed": fields_accessed or [],
            "related_authorization": related_authorization,
            "related_note": related_note,
            "related_medication": related_medication,
            "related_guideline": related_guideline,
            "timestamp": _now_iso(),
        }
        return self.insert(entry)

    def find_by_member(self, member_id):
        return list(
            self.collection.find({"member_id": member_id}).sort("timestamp", 1)
        )

    def delete_by_member(self, member_id):
        """Remove all audit entries for a member.

        Append-only is the runtime contract; this delete exists ONLY for the
        out-of-band demo reset, never for workflow code.
        """
        return self.delete_by({"member_id": member_id})
