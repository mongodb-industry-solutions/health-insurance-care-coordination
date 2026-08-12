"""API routes for the frontend-facing authorization workflow."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from db.mdb import MongoDBConnector, get_connector
from .service import AuthorizationWorkflowService
from .events import get_bus, sse, keepalive, TERMINAL_EVENTS
from .watcher import TraceWatcher
from .review import MedicalDirectorReviewService
from .models import CanStartResponse

router = APIRouter(prefix="/api", tags=["authorization"])

# Send a comment this often when nothing is happening, so browsers and proxies do not
# drop a connection during the long pauses while an LLM works.
_KEEPALIVE_SECONDS = 15
# Grace period after a terminal event, for writes that land just as the run returns.
_FINAL_DRAIN_SECONDS = 1.5

logger = logging.getLogger(__name__)


def _log_run_failure(task) -> None:
    """Surface a crash inside a detached run.

    The orchestration future is never awaited — the run has to outlive the stream — so
    without this an exception would vanish and the case would just stop.
    """
    try:
        task.result()
    except Exception as e:
        logger.exception("authorization run failed: %s", e)


def get_workflow_service(
    connector: MongoDBConnector = Depends(get_connector),
) -> AuthorizationWorkflowService:
    return AuthorizationWorkflowService(connector)


def get_review_service(
    connector: MongoDBConnector = Depends(get_connector),
) -> MedicalDirectorReviewService:
    return MedicalDirectorReviewService(connector)


# NOTE: declared above `/authorization/{trace_id}`-style routes for the same reason
# members/routes.py warns about — FastAPI matches in declaration order, so a literal
# segment placed after a path parameter is unreachable.
@router.get("/authorization/pending-review")
async def pending_review(
    service: MedicalDirectorReviewService = Depends(get_review_service),
):
    """The medical director's queue — every case awaiting a human decision.

    Derived from the traces themselves (`review.routedToHuman` set, `review.closedBy`
    still null), so it cannot drift from reality. Each entry carries the agent's
    recommendation, its confidence, why it escalated, and the case brief the agent
    assembled for the reviewer.
    """
    return service.pending_review()


@router.post("/authorization/{trace_id}/medical-director-decision")
async def medical_director_decision(
    trace_id: str,
    decision: str,
    medical_director_id: str = "MD-7781",
    notes: str = None,
    member_owed: float = 0,
    paid_amt: float = 0,
    service: MedicalDirectorReviewService = Depends(get_review_service),
):
    """Close an escalated case as the medical director.

    The other half of bounded authority: the agent assembles the case and is forbidden
    from closing it, so this is the only path by which David's clinical denial or
    Aisha's low-confidence case can ever resolve.

    `decision` is `approved` or `denied`. Diverging from the agent's recommendation is
    allowed and is recorded as an override on the trace, with `notes` kept as the
    physician's rationale.

    Then it cascades: the linked claim takes the decision, and the member's pending
    action is resolved. Both are reported in the response, and a cascade failure is
    listed in `cascade_errors` rather than raised — the physician's decision is already
    recorded by then and must not be unwound by a follow-up write.

    `medical_director_id` defaults to a demo reviewer; a real deployment would take it
    from the authenticated user rather than the query string.

    400 for an invalid decision, a case never routed to a human, or one already closed.
    404 for an unknown trace.
    """
    try:
        return service.decide(
            trace_id,
            medical_director_id=medical_director_id,
            decision=decision,
            notes=notes,
            member_owed=member_owed,
            paid_amt=paid_amt,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


@router.post("/members/{member_id}/authorization/start")
async def start_authorization(
    member_id: str,
    connector: MongoDBConnector = Depends(get_connector),
    service: AuthorizationWorkflowService = Depends(get_workflow_service),
    service_date: str = None,
):
    """Start the prior-authorization process — the "Start Process" button.

    Returns a **Server-Sent Event stream**, not a JSON body: one call, held open for
    the length of the run, pushing progress as it happens. The frontend needs no
    follow-up request and never has to learn the traceId in advance — it arrives on
    the `trace_opened` event once the agent's Step 0 creates it.

        curl -N -X POST http://localhost:8000/api/members/MBR-2026-44109/authorization/start

    Events, in the order a full run produces them:
        accepted        the case passed validation; the run is starting
        turn_started    an agent has been handed the case (fills the LLM silences)
        trace_opened    Step 0 created the trace
        step            a reasoning step was recorded
        recommendation  clinical review proposed a decision
        turn_finished   that agent's turn returned
        escalated       routed to a medical director
        closed          the case was closed
        stopped         terminal: the run reached a stopping point
        error           terminal: the run failed

    Validation still happens up front, so a bad request is an ordinary HTTP error
    rather than an error event: 404 for an unknown member, 409 when a case is already
    open. The stream only starts once the run is genuinely underway.

    Closing the connection does NOT cancel the run — the agents keep working and the
    trace keeps filling. Reconnect with the GET stream to watch again.
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

    run = result.pop("run")
    bus = get_bus()

    async def event_stream():
        queue = bus.subscribe(member_id)
        watcher = TraceWatcher(connector, bus, member_id)
        loop = asyncio.get_running_loop()

        def publish(event: str, data: dict = None):
            bus.publish(member_id, event, data)

        # The orchestrator blocks on each agent for minutes, so it runs on a thread.
        # Detached from this generator on purpose: if the viewer disconnects, the case
        # must still finish.
        task = loop.run_in_executor(None, lambda: run(publish=publish))
        # Nothing awaits that future, so an exception inside the run would otherwise be
        # swallowed and the case would simply stop with no explanation anywhere.
        task.add_done_callback(_log_run_failure)

        try:
            watcher.start()
            yield sse("accepted", {k: v for k, v in result.items() if k != "can_start"})

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    # Nothing published for a while — normal, an LLM is thinking.
                    yield keepalive()
                    continue

                yield sse(event["event"], event["data"])
                if event["event"] in TERMINAL_EVENTS:
                    # Let the watcher drain any final write (a closure recorded moments
                    # before the run returned) rather than cutting it off mid-flight.
                    await asyncio.sleep(_FINAL_DRAIN_SECONDS)
                    while not queue.empty():
                        tail = queue.get_nowait()
                        yield sse(tail["event"], tail["data"])
                    break
        finally:
            # Reached on a client disconnect too, which is why the run is not cancelled
            # here: the watcher and the subscription go away, the agents carry on.
            watcher.stop()
            bus.unsubscribe(member_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Stops nginx and friends from buffering the stream into one lump.
            "X-Accel-Buffering": "no",
        },
    )
