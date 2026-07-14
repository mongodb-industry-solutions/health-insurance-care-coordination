"""Business logic for member operations."""

from .repository import MemberRepository


class MemberService:
    """Service layer for member-related operations."""

    def __init__(self):
        self.repository = MemberRepository()

    def get_clinical_context(self, member_id: str) -> dict:
        """Retrieve member's clinical history and eligibility for decision-making."""
        doc = self.repository.get_clinical_history(member_id)
        if not doc:
            return None
        return {
            "member_id": member_id,
            "clinical_history": doc.get("clinical_history"),
            "eligibility": doc.get("eligibility"),
            "current_care_plan": doc.get("current_care_plan"),
        }

    def get_member(self, member_id: str) -> dict:
        """Retrieve complete member document."""
        return self.repository.get_by_id(member_id)

    def get_members_by_plan(self, plan_id: str) -> list:
        """Retrieve all members enrolled in a plan."""
        return self.repository.find_by_plan(plan_id)

    def list_all_members(self) -> list:
        """Retrieve all members."""
        return self.repository.find()
