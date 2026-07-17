from core.repository import Repository
from shared.collections import Collections


class MemberRepository(Repository):
    """Access to the `members` collection — the core object of the model.

    Every member document holds eligibility, clinical history, treatment
    responses and a small cross-domain summary, so most agent reads land here.
    """

    collection_name = Collections.MEMBERS

    def get_clinical_history(self, member_id):
        doc = self.collection.find_one(
            {"_id": member_id},
            {"clinical_history": 1, "eligibility": 1, "current_care_plan": 1},
        )
        return doc

    def find_by_plan(self, plan_id):
        return self.find({"plan_id": plan_id})
