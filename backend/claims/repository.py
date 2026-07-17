from core.repository import Repository
from shared.collections import Collections


class ClaimRepository(Repository):
    """Access to the `claims` collection.

    Claims are the member's adjudicated history and the source of comparable-case
    precedent (episodic memory) an agent retrieves when weighing an approval.
    """

    collection_name = Collections.CLAIMS

    def find_by_member(self, member_id):
        return self.find({"member_id": member_id})

    def delete_by_member(self, member_id):
        """Remove all claims for a member (used by demo reset)."""
        return self.delete_by({"member_id": member_id})

    def find_comparable(self, service, diagnosis, exclude_member=None, limit=3):
        """Retrieve comparable precedent: other members' APPROVED claims for the
        same service + diagnosis.

        Filters to `outcome: approved`, excludes the querying member (a member is
        not their own precedent), projects only what the agent needs to judge
        similarity, and caps the result. Exact match on service/diagnosis for now
        — see claims/service.py for the Atlas Vector Search upgrade path.
        """
        query = {"service": service, "diagnosis": diagnosis, "outcome": "approved"}
        if exclude_member:
            query["member_id"] = {"$ne": exclude_member}
        projection = {
            "service": 1,
            "outcome": 1,
            "presentation_profile": 1,
            "member_id": 1,
        }
        return list(self.collection.find(query, projection).limit(limit))
