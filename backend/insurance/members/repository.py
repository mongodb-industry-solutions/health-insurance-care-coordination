from core.repository import Repository
from shared.collections import Collections


class MemberRepository(Repository):
    """Access to the insurance `members` collection: identity, policy link, eligibility
    and the two-field summary. Nothing clinical."""

    collection_name = Collections.MEMBERS
    business_key = "memberId"

    def set_summary(self, member_id, summary_fields, now):
        """Write specific `summary.*` fields and bump `updatedAt`, leaving the rest of the
        record alone. A field-level `$set`, never a whole-document replace: a summary
        refresh must not be able to roll back a concurrent write."""
        updates = {f"summary.{k}": v for k, v in summary_fields.items()}
        updates["updatedAt"] = now
        return self.collection.update_one(
            {"memberId": member_id}, {"$set": updates}
        ).modified_count
