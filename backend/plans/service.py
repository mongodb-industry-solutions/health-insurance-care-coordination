"""Business logic for plan operations."""

from .repository import PlanRepository


class PlanService:
    """Service layer for plan-related operations."""

    def __init__(self):
        self.repository = PlanRepository()

    def get_plan(self, plan_id: str) -> dict:
        """Retrieve a plan by ID."""
        return self.repository.get_by_id(plan_id)

    def list_all_plans(self) -> list:
        """Retrieve all plans."""
        return self.repository.find()
