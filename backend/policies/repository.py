from core.repository import Repository
from shared.collections import Collections


class PolicyRepository(Repository):
    """Access to the `policies` collection.

    A Policy binds a member to a single Plan and carries the contract term and
    status. Coverage decisions resolve member -> policy -> plan.
    """

    collection_name = Collections.POLICIES

    def find_by_plan(self, plan_id):
        return self.find({"planId": plan_id})
