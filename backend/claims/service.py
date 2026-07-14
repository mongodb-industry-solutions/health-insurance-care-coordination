"""Business logic for claims and comparable case retrieval."""

from .repository import ClaimRepository


class ClaimService:
    """Service layer for claims operations.

    Provides access to adjudicated claim history and comparable case retrieval
    (episodic memory for authorization decisions).
    """

    def __init__(self):
        self.repository = ClaimRepository()

    def find_comparable_cases(self, service: str, diagnosis: str) -> list:
        """Find prior adjudicated claims with the same service and diagnosis.

        Used as episodic memory: shows precedent of similar treatments for
        similar presentations.
        """
        return self.repository.find_comparable(service, diagnosis)

    def get_member_claims(self, member_id: str) -> list:
        """Retrieve all adjudicated claims for a member."""
        return self.repository.find_by_member(member_id)

    def get_claim(self, claim_id: str) -> dict:
        """Retrieve a specific claim."""
        return self.repository.get_by_id(claim_id)

    def list_all_claims(self) -> list:
        """Retrieve all claims."""
        return self.repository.find()
