"""Business logic for clinical guidelines (procedural and taxonomic memory)."""

from db.mdb import get_connector
from .repository import GuidelineRepository


class GuidelineService:
    """Service layer for guidelines operations.

    Provides access to medical necessity criteria, taxonomic classification
    (reason by category), and procedural memory (decision gates).
    """

    def __init__(self, connector=None):
        connector = connector or get_connector()
        self.repository = GuidelineRepository(connector)

    def get_guideline_for_condition(self, condition_code: str) -> dict:
        """Retrieve the latest guideline for a condition (Phase 1, step 4).

        Returns taxonomic classification and procedural criteria that agents use to
        evaluate medical necessity. The exact version consulted is captured on the
        decision trace's `contextSnapshot.guidelineRef` when the case is processed.
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

    @staticmethod
    def _therapy_key(guideline: dict, requested: str) -> str:
        """Resolve the classification key for a requested therapy.

        `classification` is keyed by therapy name (e.g. "secukinumab"), but callers
        pass either that name or the full service string (e.g.
        "biologic therapy - secukinumab"). Try an exact match, then the token after
        the last " - ", then a case-insensitive scan of the classification keys.
        """
        classification = guideline.get("classification", {})
        if not requested:
            return requested
        if requested in classification:
            return requested
        tail = requested.split(" - ")[-1].strip()
        if tail in classification:
            return tail
        for key in classification:
            if key.lower() == tail.lower() or key.lower() == requested.lower():
                return key
        return tail

    def evaluate_coverage_tier(self, guideline: dict, requested_service: str) -> dict:
        """Evaluate whether a requested service meets coverage tier requirements.

        Resolves the therapy name from the requested service so classification —
        which is keyed by therapy name, not the full service string — is found.
        """
        classification = guideline.get("classification", {})
        key = self._therapy_key(guideline, requested_service)
        service_class = classification.get(key, {})

        return {
            "service": requested_service,
            "therapy": key,
            "tier": service_class.get("tier", "unknown"),
            "prior_auth_required": service_class.get("prior_auth_required", False),
            "class": service_class.get("class", "unknown"),
        }

    def get_step_therapy_requirement(self, guideline: dict) -> dict:
        """Extract step therapy requirement from guideline."""
        criteria = guideline.get("criteria", {})
        step_therapy = criteria.get("step_therapy", {})
        return step_therapy or None
