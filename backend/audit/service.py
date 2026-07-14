"""Business logic for audit logging and compliance."""

from .repository import AuditRepository


class AuditService:
    """Service layer for audit operations.

    Every agent interaction with a member record is logged to an append-only
    audit trail so regulators can reconstruct what was accessed, by which agent,
    and why.
    """

    def __init__(self):
        self.repository = AuditRepository()

    def log_action(
        self,
        member_id: str,
        agent: str,
        action: str,
        fields_accessed: list = None,
        related_authorization: str = None,
    ) -> str:
        """Log an agent action to the audit trail."""
        return self.repository.record(
            member_id=member_id,
            agent=agent,
            action=action,
            fields_accessed=fields_accessed or [],
            related_authorization=related_authorization,
        )

    def get_member_audit_trail(self, member_id: str) -> list:
        """Retrieve the complete audit trail for a member.

        Sorted chronologically so regulators can reconstruct the sequence
        of events and decisions.
        """
        return self.repository.find_by_member(member_id)

    def log_clinical_context_read(self, member_id: str, related_auth: str = None):
        """Log that clinical context was read."""
        return self.log_action(
            member_id=member_id,
            agent="pathway_agent",
            action="read_clinical_context",
            fields_accessed=["clinical_history", "eligibility"],
            related_authorization=related_auth,
        )

    def log_guideline_check(self, member_id: str, condition: str, related_auth: str = None):
        """Log that a guideline was checked."""
        return self.log_action(
            member_id=member_id,
            agent="pathway_agent",
            action="check_guideline",
            fields_accessed=[],
            related_authorization=related_auth,
        )

    def log_comparable_case_search(self, member_id: str, related_auth: str = None):
        """Log that comparable cases were retrieved."""
        return self.log_action(
            member_id=member_id,
            agent="pathway_agent",
            action="search_comparable_cases",
            fields_accessed=[],
            related_authorization=related_auth,
        )
