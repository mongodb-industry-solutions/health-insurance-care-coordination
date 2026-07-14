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

    def find_comparable(self, service, diagnosis):
        """Retrieve prior adjudicated claims with the same service + diagnosis."""
        return self.find({"service": service, "diagnosis": diagnosis})
