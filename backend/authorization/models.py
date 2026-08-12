"""Response shapes for the authorization workflow endpoints."""

from typing import Optional
from pydantic import BaseModel


class AgentTarget(BaseModel):
    """Where the run was sent, surfaced so a demo operator can tell at a glance
    whether anything was actually invoked."""
    mode: str          # dry_run | http
    agent: str         # insurance | care_coordination
    url: str


class StartAuthorizationResponse(BaseModel):
    """Answer to the member's "Start Process" click.

    Returns as soon as the agent has been handed the case — the run itself continues
    in the background for minutes.

    `trace_id` and `claim_id` are always null here: the Insurance Agent creates both
    during Step 0, after this response is already on its way. The frontend picks them
    up from the progress stream.
    """
    status: str                            # "starting"
    member_id: str
    action_id: str
    proposed_treatment: Optional[str] = None
    related_diagnosis_code: Optional[str] = None
    raised_by: Optional[str] = None
    service_date: str
    agent: AgentTarget
    # The exact message handed to the agent. Kept in the response because it is the
    # one thing that is otherwise invisible when a run misbehaves.
    agent_message: str
    trace_id: Optional[str] = None
    claim_id: Optional[str] = None
    detail: str


class CurrentCaseResponse(BaseModel):
    """Which trace a member's case is running on.

    Exists because `start` cannot return a `trace_id` — the agent mints it during
    Step 0, after the 202 has been sent. Carries no trace contents: fetch those from
    `GET /api/audit/traces/{trace_id}`.
    """
    member_id: str
    has_case: bool
    trace_id: Optional[str] = None
    status: Optional[str] = None
    is_closed: Optional[bool] = None
    detail: str


class CanStartResponse(BaseModel):
    """Whether "Start Process" may fire, with no side effects — lets the frontend
    disable the button instead of discovering a 409 on click."""
    can_start: bool
    member_id: str
    reason: Optional[str] = None           # no_pending_action | already_in_progress
    trace_id: Optional[str] = None
    trace_status: Optional[str] = None
    detail: Optional[str] = None
