from core.repository import Repository
from shared.collections import Collections


class NotificationRepository(Repository):
    """Access to the `notifications` collection.

    Member-facing notifications. Inserts here are what a change stream watches so a
    frontend can surface notifications in real time (SSE endpoint — next step).
    """

    collection_name = Collections.NOTIFICATIONS

    def find_by_member(self, member_id):
        return list(
            self.collection.find({"memberId": member_id}).sort("createdAt", 1)
        )

    def delete_by_member(self, member_id):
        """Remove a member's notifications (used by demo reset)."""
        return self.delete_by({"memberId": member_id})
