"""Business logic for plan operations."""

from db.mdb import get_connector
from .repository import PlanRepository


class PlanService:
    """Service layer for plan-related operations."""

    def __init__(self, connector=None):
        self.repository = PlanRepository(connector or get_connector())

    def get_plan(self, plan_id: str) -> dict:
        """Retrieve a plan by ID."""
        return self.repository.get_by_key(plan_id)

    def list_all_plans(self) -> list:
        """Retrieve all plans."""
        return self.repository.find()
