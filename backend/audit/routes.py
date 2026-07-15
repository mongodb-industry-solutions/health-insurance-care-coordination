"""API routes for audit logging."""

from fastapi import APIRouter, Depends
from typing import List

from db.mdb import MongoDBConnector, get_connector
from .service import AuditService
from .models import LogActionResponse, MemberAuditTrailResponse

router = APIRouter(prefix="/api/audit", tags=["audit"])


def get_audit_service(connector: MongoDBConnector = Depends(get_connector)) -> AuditService:
    return AuditService(connector)


@router.post("/log", response_model=LogActionResponse)
async def log_agent_action(
    member_id: str,
    agent: str,
    action: str,
    fields_accessed: List[str] = None,
    related_authorization: str = None,
    service: AuditService = Depends(get_audit_service),
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


@router.get("/member/{member_id}", response_model=MemberAuditTrailResponse)
async def get_member_audit_trail(
    member_id: str, service: AuditService = Depends(get_audit_service)
):
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
