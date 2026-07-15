"""API routes for member operations."""

from fastapi import APIRouter, Depends, HTTPException
from typing import Union

from db.mdb import MongoDBConnector, get_connector
from .service import MemberService
from .models import Member, MemberClinicalContext, MemberList

router = APIRouter(prefix="/api/members", tags=["members"])


def get_member_service(connector: MongoDBConnector = Depends(get_connector)) -> MemberService:
    return MemberService(connector)


@router.get("/{member_id}", response_model=Member)
async def get_member(member_id: str, service: MemberService = Depends(get_member_service)):
    """Retrieve a complete member document."""
    doc = service.get_member(member_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return doc


@router.get("/{member_id}/clinical-context", response_model=MemberClinicalContext)
async def get_member_clinical_context(
    member_id: str, service: MemberService = Depends(get_member_service)
):
    """Retrieve member's clinical history and eligibility."""
    context = service.get_clinical_context(member_id)
    if not context:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return context


@router.get("", response_model=Union[MemberList, list])
async def list_members(
    plan_id: str = None, service: MemberService = Depends(get_member_service)
):
    """List members, optionally filtered by plan."""
    if plan_id:
        members = service.get_members_by_plan(plan_id)
        return {"count": len(members), "members": members}
    members = service.list_all_members()
    return {"count": len(members), "members": members}
