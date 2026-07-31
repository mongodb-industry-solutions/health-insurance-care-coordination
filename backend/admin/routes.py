"""Admin / demo routes: seed and reset synthetic data.

Namespaced under /api/admin to mark it as privileged tooling, distinct from the
product domains. These endpoints write and delete data (including audit rows) and
should be locked down or removed for production.
"""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_connector
from .service import AdminService

router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_admin_service(connector: MongoDBConnector = Depends(get_connector)) -> AdminService:
    return AdminService(connector)


@router.post("/seed")
async def seed_canonical(service: AdminService = Depends(get_admin_service)):
    """Load the canonical profiles (idempotent upsert; nothing is wiped)."""
    return service.seed_canonical()


@router.post("/reset")
async def reset_all(service: AdminService = Depends(get_admin_service)):
    """Wipe the seeded collections and reseed the canonical set."""
    return service.reset_all()


@router.post("/members/{member_id}/reset")
async def reset_member(
    member_id: str, service: AdminService = Depends(get_admin_service)
):
    """Restore a single member to baseline without touching other members."""
    try:
        return service.reset_member(member_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
