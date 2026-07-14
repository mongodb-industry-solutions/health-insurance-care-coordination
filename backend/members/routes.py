"""API routes for member operations."""

from fastapi import APIRouter, HTTPException

from .service import MemberService

router = APIRouter(prefix="/api/members", tags=["members"])
service = MemberService()


@router.get("/{member_id}")
async def get_member(member_id: str):
    """Retrieve a complete member document."""
    doc = service.get_member(member_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return doc


@router.get("/{member_id}/clinical-context")
async def get_member_clinical_context(member_id: str):
    """Retrieve member's clinical history and eligibility."""
    context = service.get_clinical_context(member_id)
    if not context:
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return context


@router.get("")
async def list_members(plan_id: str = None):
    """List members, optionally filtered by plan."""
    if plan_id:
        return service.get_members_by_plan(plan_id)
    return service.list_all_members()
