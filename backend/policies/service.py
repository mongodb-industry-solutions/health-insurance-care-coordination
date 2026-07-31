"""Business logic for policy operations."""

from db.mdb import get_connector
from plans.repository import PlanRepository
from .repository import PolicyRepository


class PolicyService:
    """Service layer for policy-related operations."""

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = PolicyRepository(connector)
        self.plan_repo = PlanRepository(connector)

    def get_policy(self, policy_id: str) -> dict:
        """Retrieve a policy by its policy number (_id)."""
        return self.repository.get_by_id(policy_id)

    def list_all_policies(self) -> list:
        return self.repository.find()

    def get_plan_for_policy(self, policy_id: str) -> dict:
        """Resolve the Plan a policy is enrolled in (member -> policy -> plan)."""
        policy = self.repository.get_by_id(policy_id)
        if not policy:
            return None
        return self.plan_repo.get_by_id(policy.get("planId"))
