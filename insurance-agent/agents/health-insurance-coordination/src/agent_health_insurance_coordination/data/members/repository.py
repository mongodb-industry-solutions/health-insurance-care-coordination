from ..core.repository import Repository
from ..shared.collections import Collections


class MemberRepository(Repository):
    """Access to the `members` collection — the core object of the model.

    Every member document holds eligibility, clinical history, treatment
    responses and a small cross-domain summary, so most agent reads land here.
    A member references a Policy (`policyId`), which in turn references a Plan.
    """

    collection_name = Collections.MEMBERS
    business_key = "memberId"

    def get_clinical_history(self, member_id):
        doc = self.collection.find_one(
            {"memberId": member_id},
            {"memberId": 1, "clinical_history": 1, "eligibility": 1,
             "current_care_plan": 1},
        )
        return doc

    def find_by_policy(self, policy_id):
        return self.find({"policyId": policy_id})

    # Statuses that mean a pending action is still the platform's problem.
    # `resolved` is excluded; `in_progress` is not, because an escalated case sits
    # there indefinitely while a medical director owes a decision, and it must stay
    # visible on the queue rather than looking finished.
    OPEN_ACTION_STATUSES = ("pending", "in_progress")

    def find_with_open_pending_actions(self):
        """Members with at least one unresolved `pendingActions[]` entry.

        This is the agent's work queue. Projected to the queue's needs — identity,
        the rolling summary, and the actions themselves — rather than the whole
        record: it backs a list view, and pulling full clinical histories and
        encrypted PHI blobs for every open case is both slower and more exposure
        than the view requires.
        """
        return list(
            self.collection.find(
                {"pendingActions.status": {"$in": list(self.OPEN_ACTION_STATUSES)}},
                {
                    "_id": 0,
                    "memberId": 1,
                    "firstName": 1,
                    "lastName": 1,
                    "policyId": 1,
                    "summary": 1,
                    "pendingActions": 1,
                },
            )
        )

    def update_pending_action(self, member_id, action_id, updates):
        """Update one entry of `pendingActions[]` in place.

        Uses a positional (`$`) update matched on both the member and the action id,
        so only the addressed entry's fields are written. The alternative the rest
        of this codebase uses — read the member, mutate, replace the whole document
        — would silently discard any concurrent write to another part of the record,
        and would need an `_id` that the final data model leaves as a
        MongoDB-assigned ObjectId.

        Returns the number of documents modified: 0 means nothing matched.
        """
        return self.collection.update_one(
            {"memberId": member_id, "pendingActions.actionId": action_id},
            {"$set": {f"pendingActions.$.{k}": v for k, v in updates.items()}},
        ).modified_count

    def touch(self, member_id, timestamp):
        """Bump the record's own `updatedAt`, without touching `summary.updated_at`.

        The two are different facts: `updatedAt` is when the record last changed,
        `summary.updated_at` is when the rolling projection was last recalculated.
        A pending-action transition is the former, not the latter.
        """
        return self.collection.update_one(
            {"memberId": member_id}, {"$set": {"updatedAt": timestamp}}
        ).modified_count

    def set_summary(self, member_id, summary_fields):
        """Write specific `summary.*` fields, leaving the rest of the record alone.

        Field-level `$set` rather than a whole-document replace, for the same reason
        as `update_pending_action`: a summary refresh must never be able to roll
        back a clinical write that happened in between.
        """
        updates = {f"summary.{k}": v for k, v in summary_fields.items()}
        return self.collection.update_one(
            {"memberId": member_id}, {"$set": updates}
        ).modified_count
