from core.repository import Repository
from shared.collections import Collections


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
