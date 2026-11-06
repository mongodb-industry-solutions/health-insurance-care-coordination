"""Business logic for policy operations.

Read-only. The eligibility check (`verify_eligibility_on_date`) is the Insurance Agent's own
gate and runs inside the agent against the same collection; the backend only serves the
policy record.
"""

from typing import Optional

from .repository import PolicyRepository


class PolicyService:
    """Service layer for policy-related operations."""

    def __init__(self, connector):
        self.repository = PolicyRepository(connector)

    def get_policy(self, policy_id: str) -> Optional[dict]:
        """Retrieve a policy by its policyId; None if not found."""
        return self.repository.get_by_key(policy_id)
