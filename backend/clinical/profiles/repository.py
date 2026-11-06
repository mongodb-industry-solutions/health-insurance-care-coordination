from core.repository import Repository
from shared.collections import ClinicalCollections


class ProfileRepository(Repository):
    """Access to the clinical `clinical_profiles` collection (one per member)."""

    collection_name = ClinicalCollections.CLINICAL_PROFILES
    business_key = "memberId"

    def set_action_fields(self, member_id, action_id, fields, only_if=None) -> int:
        """Update one `pendingActions[]` entry in place with a positional (`$`) update.

        Matched on both the member and the action id so only the addressed entry's fields
        are written; the alternative (read, mutate, replace the document) would discard a
        concurrent write to another part of the profile. `only_if` adds extra match
        conditions on the entry (e.g. `{"status": "pending"}`) so the write is a
        compare-and-set. Returns the modified count: 0 means nothing matched, or the entry
        already held those values.
        """
        element = {"actionId": action_id, **(only_if or {})}
        return self.collection.update_one(
            {"memberId": member_id, "pendingActions": {"$elemMatch": element}},
            {"$set": {f"pendingActions.$.{k}": v for k, v in fields.items()}},
        ).modified_count

    def set_care_plan_fields(self, member_id, fields, now) -> int:
        """Field-level `$set` on `current_care_plan.*`, plus `updatedAt`."""
        updates = {f"current_care_plan.{k}": v for k, v in fields.items()}
        updates["updatedAt"] = now
        return self.collection.update_one({"memberId": member_id}, {"$set": updates}).modified_count

    def touch(self, member_id, now) -> int:
        return self.collection.update_one(
            {"memberId": member_id}, {"$set": {"updatedAt": now}}
        ).modified_count
