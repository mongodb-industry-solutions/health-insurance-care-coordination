"""Business logic for clinical guidelines (procedural and taxonomic memory)."""

from db.mdb import get_connector
from .repository import GuidelineRepository


class GuidelineService:
    """Service layer for guidelines operations.

    Provides access to medical necessity criteria, taxonomic classification
    (reason by category), and procedural memory (decision gates).
    """

    def __init__(self, connector=None):
        self.repository = GuidelineRepository(connector or get_connector())

    def get_guideline_for_condition(self, condition_code: str) -> dict:
        """Retrieve the latest guideline for a condition.

        Returns taxonomic classification and procedural criteria that agents
        use to evaluate medical necessity.
        """
        return self.repository.latest_for_condition(condition_code)

    def get_all_guidelines_for_condition(self, condition_code: str) -> list:
        """Retrieve all guideline versions for a condition (newest first)."""
        return self.repository.find_by_condition(condition_code)

    def get_guideline(self, guideline_id: str) -> dict:
        """Retrieve a specific guideline by ID."""
        return self.repository.get_by_id(guideline_id)

    def list_all_guidelines(self) -> list:
        """Retrieve all guidelines."""
        return self.repository.find()

    def evaluate_coverage_tier(self, guideline: dict, requested_service: str) -> dict:
        """Evaluate whether a requested service meets coverage tier requirements."""
        classification = guideline.get("classification", {})
        service_class = classification.get(requested_service, {})

        return {
            "service": requested_service,
            "tier": service_class.get("tier", "unknown"),
            "prior_auth_required": service_class.get("prior_auth_required", False),
            "class": service_class.get("class", "unknown"),
        }

    def get_step_therapy_requirement(self, guideline: dict) -> dict:
        """Extract step therapy requirement from guideline."""
        criteria = guideline.get("criteria", {})
        step_therapy = criteria.get("step_therapy", {})
        return step_therapy or None
