"""Business logic for clinical guidelines (procedural and taxonomic memory)."""

from db.mdb import get_connector
from audit.repository import AuditRepository
from .repository import GuidelineRepository


class GuidelineService:
    """Service layer for guidelines operations.

    Provides access to medical necessity criteria, taxonomic classification
    (reason by category), and procedural memory (decision gates).
    """

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = GuidelineRepository(connector)
        # Cross-cutting audit of agent reads (see MemberService for the rationale).
        self.audit = AuditRepository(connector)

    def get_guideline_for_condition(
        self, condition_code: str, agent: str = None, member_id: str = None
    ) -> dict:
        """Retrieve the latest guideline for a condition.

        Returns taxonomic classification and procedural criteria that agents
        use to evaluate medical necessity. Phase 1, step 4.

        Guidelines are reference data, but a read done as part of an agent's work
        on a case is audited against that member (step 4a). Logging requires both
        `agent` and `member_id`; `related_guideline` records the exact version
        consulted — the CMS decision trace needs that.
        """
        guideline = self.repository.latest_for_condition(condition_code)
        if guideline and agent and member_id:
            self.audit.record(
                member_id=member_id,
                agent=agent,
                action="read guideline",
                fields_accessed=["criteria", "classification", "confidence_threshold"],
                related_guideline=guideline.get("_id"),
            )
        return guideline

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
