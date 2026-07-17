from core.repository import Repository
from shared.collections import Collections


class AuthorizationRepository(Repository):
    """Access to the `authorizations` collection.

    Each authorization carries a decision_trace (the reasoning the CMS rule
    requires) and a review block encoding bounded authority — denials must be
    closed by a medical director, never the agent alone.
    """

    collection_name = Collections.AUTHORIZATIONS

    def find_by_member(self, member_id):
        return self.find({"member_id": member_id})

    def find_pending_by_member(self, member_id):
        """The member's most recently filed, not-yet-decided authorization."""
        pending = self.find({"member_id": member_id, "status": "pending"})
        return max(pending, key=lambda a: a.get("created_at", ""), default=None)

    def delete_by_member(self, member_id):
        """Remove all authorizations for a member (used by demo reset)."""
        return self.delete_by({"member_id": member_id})

    def find_routed_to_human(self):
        return self.find({"review.routed_to_human": True})
