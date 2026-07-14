"""API routes for audit logging."""

from fastapi import APIRouter

from .service import AuditService

router = APIRouter(prefix="/api/audit", tags=["audit"])
service = AuditService()


@router.post("/log")
async def log_agent_action(
    member_id: str,
    agent: str,
    action: str,
    fields_accessed: list = None,
    related_authorization: str = None,
):
    """Log an agent action to the audit trail.

    Every interaction with a member record is logged so regulators can
    reconstruct what was accessed, by which agent, and why.
    """
    service.log_action(
        member_id=member_id,
        agent=agent,
        action=action,
        fields_accessed=fields_accessed or [],
        related_authorization=related_authorization,
    )
    return {
        "status": "logged",
        "member_id": member_id,
        "action": action,
    }


@router.get("/member/{member_id}")
async def get_member_audit_trail(member_id: str):
    """Retrieve the complete audit trail for a member.

    Sorted chronologically so regulators can reconstruct the sequence
    of events and decisions.
    """
    entries = service.get_member_audit_trail(member_id)
    return {
        "member_id": member_id,
        "entry_count": len(entries),
        "entries": entries,
    }
