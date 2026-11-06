"""Admin / demo routes: seed and reset synthetic data.

Served at the root (`/seed`, `/reset-demo`, `/members/{member_id}/reset-demo`) rather than
under the `/api` prefix the product domains use — short to type during a demo, and
the absence of the prefix is itself a marker that these are not product endpoints.

`main.py` mounts this router a second time under `/api/admin` for the frontend's
"Reset demo" button: the browser reaches the backend only through the Next.js
`/api/*` proxy, which would not forward a root path. Same handlers, two paths.

They write and delete data, including the audit rows this is the only code allowed
to remove, and `/reset-demo` discards every member's state. Lock them down or drop
the router entirely for anything but a demo.
"""

from fastapi import APIRouter, Depends, HTTPException

from db.mdb import MongoDBConnector, get_clinical_connector, get_insurance_connector
from .service import AdminService

router = APIRouter(prefix="", tags=["admin"])


def get_admin_service(
    insurance: MongoDBConnector = Depends(get_insurance_connector),
    clinical: MongoDBConnector = Depends(get_clinical_connector),
) -> AdminService:
    return AdminService(insurance, clinical)


@router.post("/seed")
async def seed_canonical(service: AdminService = Depends(get_admin_service)):
    """Load the canonical fixtures into both databases (idempotent upsert; nothing is wiped)."""
    return service.seed_canonical()


@router.post("/reset-demo")
async def reset_all(service: AdminService = Depends(get_admin_service)):
    """Rebuild the whole demo dataset from scratch — the blunt instrument.

    Deletes every document from the seeded collections in BOTH databases (insurance:
    members, policies, plans, claims, audit_log, admin_reasoning; clinical:
    clinical_profiles, dispense_history, guidelines, clinical_reasoning), then reseeds the
    canonical six members plus the shared catalog from the fixtures. Nothing is preserved,
    including audit rows this is otherwise the only code allowed to delete.

    Reach for it when the shared data has drifted or a schema change has made existing
    documents stale. For replaying one member's scenario after a demo run, use
    `/members/{member_id}/reset-demo` — it leaves the other five alone.

    Returns the delete count per collection alongside what was seeded, so the response
    is the receipt: an unexpected count means the database held more than you thought.
    """
    return service.reset_all()


@router.post("/members/{member_id}/reset-demo")
async def reset_member(
    member_id: str, service: AdminService = Depends(get_admin_service)
):
    """Restore one member to a clean pre-process state so their scenario replays.

    Deletes the member's traces, the reasoning text of those traces on both sides, and the
    claims the last run added, then re-upserts the baseline from the fixtures: the insurance
    record (`summary.open_authorization_count` back to 0, `last_authorization_status` back to
    `none`) and the clinical profile (`pendingActions[]` back to `pending` with
    `linkedAuditTraceId` null, the care plan and any `gap_reviewed` entry back to baseline).

    Other members are untouched, as are the shared plans, guidelines and precedent
    claims. Use `POST /reset-demo` when the shared catalog needs rebuilding too.

    404 when the id has no canonical profile — including a member that exists in the
    database but was not seeded from one, since there is no baseline to restore.
    """
    try:
        return service.reset_member(member_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
