from core.repository import Repository
from shared.collections import Collections


class ClaimRepository(Repository):
    """Access to the `claims` collection: the member's claim history and the financial
    record the Insurance Agent opens and settles for each prior authorization."""

    collection_name = Collections.CLAIMS
    business_key = "claimId"

    def find_by_member(self, member_id):
        return self.find({"memberId": member_id})

    def find_by_trace(self, trace_id):
        """Claims stamped with a trace id (the agent links them when it opens the case)."""
        return self.find({"linkedAuditTraceId": trace_id})

    def update_fields(self, claim_id, updates):
        """Write specific top-level fields on a claim.

        Field-level `$set` rather than a whole-document replace, so an outcome write cannot
        roll back a concurrent change to an unrelated field. Returns the number of
        documents modified; 0 means no claim matched.
        """
        return self.collection.update_one(
            {"claimId": claim_id}, {"$set": updates}
        ).modified_count

    def delete_by_member(self, member_id):
        """Remove all claims for a member (used by demo reset)."""
        return self.delete_by({"memberId": member_id})
