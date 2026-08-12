"""API routes for the frontend-facing authorization workflow."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from db.mdb import MongoDBConnector, get_connector
from .service import AuthorizationWorkflowService
from .models import StartAuthorizationResponse, CanStartResponse

router = APIRouter(prefix="/api", tags=["authorization"])


def get_workflow_service(
    connector: MongoDBConnector = Depends(get_connector),
) -> AuthorizationWorkflowService:
    return AuthorizationWorkflowService(connector)


@router.get(
    "/members/{member_id}/authorization/can-start",
    response_model=CanStartResponse,
)
async def check_can_start(
    member_id: str,
    service: AuthorizationWorkflowService = Depends(get_workflow_service),
):
    """Can this member's process be started? No side effects.

    For rendering the Start Process button in the right state. 404s only for an
    unknown member — "already running" and "nothing to start" are legitimate answers
    with `can_start: false`.
    """
    result = service.check_can_start(member_id)
    if result.get("reason") == "member_not_found":
        raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
    return result


@router.post(
    "/members/{member_id}/authorization/start",
    response_model=StartAuthorizationResponse,
    status_code=202,
)
async def start_authorization(
    member_id: str,
    background_tasks: BackgroundTasks,
    service: AuthorizationWorkflowService = Depends(get_workflow_service),
    service_date: str = None,
):
    """Start the prior-authorization process — the "Start Process" button.

    202, not 200: the work has been accepted, not completed. The Insurance Agent's
    `/invoke` blocks for the length of the whole run, so it is scheduled as a
    background task and this returns as soon as the case has been validated.

    Step 0 belongs to the agent, so this endpoint writes nothing: it does not flip
    the pending action, open the claim, or open the trace. That is why the response
    carries no `traceId` — watch the member to pick it up once Step 0 lands.

    409 when a case is already open, carrying the existing `traceId` in `detail` so a
    double-click lands the operator on the running case instead of an error.
    """
    result = service.start(member_id, service_date=service_date)

    if not result.get("can_start"):
        reason = result.get("reason")
        if reason == "member_not_found":
            raise HTTPException(status_code=404, detail=f"Member {member_id} not found")
        raise HTTPException(
            status_code=409,
            detail=result.get("detail") or f"Cannot start a case for {member_id} ({reason}).",
        )

    # Scheduled rather than awaited: BackgroundTasks run after the response is sent,
    # which is what makes this endpoint return in milliseconds while the agent works.
    background_tasks.add_task(result.pop("run"))
    return result
