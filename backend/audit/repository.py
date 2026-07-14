from datetime import datetime, timezone

from core.repository import Repository
from shared.collections import Collections


class AuditRepository(Repository):
    """Access to the append-only `audit_log` collection.

    Every agent interaction with a member record lands here so a regulator can
    reconstruct what was accessed, by which agent, and why.
    """

    collection_name = Collections.AUDIT_LOG

    def record(self, member_id, agent, action, fields_accessed=None,
               related_authorization=None):
        entry = {
            "member_id": member_id,
            "agent": agent,
            "action": action,
            "fields_accessed": fields_accessed or [],
            "related_authorization": related_authorization,
            "timestamp": datetime.now(timezone.utc),
        }
        return self.insert(entry)

    def find_by_member(self, member_id):
        return list(
            self.collection.find({"member_id": member_id}).sort("timestamp", 1)
        )
