"""Response shapes for the authorization workflow endpoints."""

from typing import Optional
from pydantic import BaseModel


class CanStartResponse(BaseModel):
    """Whether "Start Process" may fire, with no side effects — lets the frontend
    disable the button instead of discovering a 409 on click."""
    can_start: bool
    member_id: str
    reason: Optional[str] = None           # no_pending_action | already_in_progress
    trace_id: Optional[str] = None
    trace_status: Optional[str] = None
    detail: Optional[str] = None
