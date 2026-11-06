"""Business logic for plan operations.

Read-only. The treatment-coverage check is the Insurance Agent's own gate and runs inside
the agent against the same collection; the backend only serves the plan records.
"""

from .repository import PlanRepository


class PlanService:
    """Service layer for plan-related operations."""

    def __init__(self, connector):
        self.repository = PlanRepository(connector)

    def get_plan(self, plan_id: str) -> dict:
        """Retrieve a plan by ID."""
        return self.repository.get_by_key(plan_id)

    def list_all_plans(self) -> list:
        """Retrieve all plans."""
        return self.repository.find()
