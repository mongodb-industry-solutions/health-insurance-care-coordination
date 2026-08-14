"""API routes for the member-facing chat.

Separate from `authorization/routes.py` on purpose. The authorization stream reports on a
workflow whose state lives in `audit_log`; this one is a plain conversation with an agent
and writes nothing. Sharing a router would imply a relationship that does not exist.
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import agents
from .service import stream_turn

router = APIRouter(prefix="/api/chat", tags=["chat"])

logger = logging.getLogger(__name__)


class ChatTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    # Absent on the first turn of a conversation. Present thereafter, which is what gives
    # the agent memory of what was said earlier.
    session_id: str | None = None


@router.get("/agents")
async def list_agents():
    """GET /api/chat/agents — the picker's options. No credentials, no URLs."""
    return {"agents": agents.public_list(), "default": agents.DEFAULT_AGENT}


@router.post("/{agent_id}/stream")
async def stream_chat(agent_id: str, body: ChatTurnRequest):
    """POST /api/chat/{agent_id}/stream — one turn, streamed back as `text/event-stream`.

    Events: `accepted`, `activity` (tool progress), `token` (answer text),
    `done` (terminal, carries `sessionId`), `failed` (terminal).

    An unknown `agent_id` is a 404 rather than a fallback to the default agent — a reply
    attributed to an agent that never produced it is worse than no reply.
    """
    if not agents.is_known(agent_id):
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")

    # Validation happens here, before the first byte goes out, so the browser can throw
    # on a bad request instead of having to discover it as an in-stream event.
    return StreamingResponse(
        stream_turn(agent_id, body.message, body.session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Stops nginx and friends buffering the stream into one lump on delivery.
            "X-Accel-Buffering": "no",
        },
    )
