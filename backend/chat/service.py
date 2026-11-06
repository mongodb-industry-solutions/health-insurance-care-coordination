"""Chat transport: one user message in, a stream of SSE frames out.

Why this lives in the backend rather than the browser calling an agent directly:

  * the agents are reached with a service-account token, which must never reach the browser;
  * it keeps *one* definition of the agent transport, shared with the authorization workflow
    (`shared/aae_client.py`), so there is a single seam to cut when the platform changes.

The upstream frame shape is Atlas Agent Engine's `invokeStream`: `data:` lines, each a JSON
object tagged with a `chunk_type` (`text`, `step`, `done`, `error`, and `subagent_start` /
`subagent_end`). This module translates it into the `event:`/`data:` framing the frontend
already parses for the authorization run, so the browser has exactly one SSE dialect to
understand.

Everything here is deliberately synchronous. FastAPI iterates a sync generator passed to
`StreamingResponse` on its threadpool, so blocking reads never touch the event loop, and it
avoids adding an async HTTP dependency.
"""

import json
import logging
import re

from shared.aae_client import AgentEngineConfigurationError, AgentEngineError, get_client

logger = logging.getLogger(__name__)

# A chat turn is a single question, not a whole prior-auth run, so this is far shorter than the
# workflow's 900s. It is the socket read timeout: long enough for a slow tool call, short
# enough that a wedged agent surfaces as an error instead of a spinner that never resolves.
_TIMEOUT_SECONDS = 180

_SSE_DATA_PREFIX = "data: "
_SSE_DONE_SENTINEL = "[DONE]"


def sse(event: str, data: dict) -> str:
    """One SSE frame. The blank line terminates it — without it the browser buffers."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _frame_session_id(parsed: dict):
    """A session id carried in the frame itself, if the platform puts one there."""
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    return parsed.get("session_id") or metadata.get("session_id")


def _translate(parsed: dict, session_id: str = None) -> tuple[str, dict] | None:
    """One upstream `chunk_type` frame → one of our SSE events, or None to ignore.

    Unknown chunk types are dropped rather than forwarded: the platform adds new ones over time
    and an unrecognised frame is never worth showing to a member. That includes the sub-agent
    frames.
    """
    kind = parsed.get("chunk_type")

    if kind == "text":
        content = parsed.get("content") or ""
        return ("token", {"content": content}) if content else None

    # A tool's progress update. (`progress` was the previous platform's name for it.)
    if kind in ("step", "progress"):
        return "activity", {"content": parsed.get("content") or ""}

    if kind == "error":
        detail = (
            parsed.get("content")
            or parsed.get("error")
            or parsed.get("message")
            or "The agent reported an error."
        )
        return "failed", {"detail": _readable_error(detail)}

    if kind == "done":
        # The conversation handle is the *session* id the platform returned in the
        # `X-Session-ID` header, not the execution id (an execution is one turn).
        return "done", {"sessionId": _frame_session_id(parsed) or session_id}

    return None


def _readable_error(raw) -> str:
    """Upstream provider errors arrive as Python-repr strings rather than JSON
    (e.g. `Error code: 400 - {'error': {'message': "...", ...}}`). Pull out the human
    half when the shape matches, and fall back to the raw text when it does not."""
    if not isinstance(raw, str):
        return str(raw)

    match = re.search(r"'message':\s*\"([^\"]*)\"", raw)
    return match.group(1) if match else raw


def _iter_stream_frames(response, fallback_session_id: str = None):
    """Yield translated events from a live SSE response.

    Reads line-wise off the socket so tokens reach the browser as they are produced;
    `response` is a file-like object, and iterating it blocks per line rather than buffering
    the whole body. The session id comes from the response header; if the platform does not
    send one on a stream, the session this turn was started with is carried forward.
    """
    session_id = response.headers.get("X-Session-ID") or fallback_session_id

    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line or line.startswith(":"):
            continue

        payload = line[len(_SSE_DATA_PREFIX):] if line.startswith(_SSE_DATA_PREFIX) else line
        if payload == _SSE_DONE_SENTINEL:
            continue

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            # The engine occasionally emits bare text with no JSON envelope. Treat it as
            # content rather than dropping it — losing part of an answer is worse than
            # showing an odd fragment.
            yield "token", {"content": payload}
            continue

        translated = _translate(parsed, session_id)
        if translated:
            yield translated


def stream_turn(agent_id: str, message: str, session_id: str | None = None):
    """Drive one chat turn and yield ready-to-send SSE frames.

    Never raises: a failed turn has to arrive as a `failed` event on an already-open stream,
    because the response headers went out long before the agent answered. The stream always
    ends on `done` or `failed`, which is what lets the browser stop reading.
    """
    yield sse("accepted", {"agent": agent_id})

    saw_terminal = False
    response = None
    try:
        # Inside the try: a missing credential must arrive as a `failed` event too, not an
        # exception escaping the generator after headers are sent.
        try:
            response = get_client().open_stream(agent_id, message, session_id, timeout=_TIMEOUT_SECONDS)
        except AgentEngineConfigurationError as e:
            # Names the missing variables, never a value.
            logger.error("chat: agent %s misconfigured: %s", agent_id, e)
            yield sse("failed", {"detail": str(e)})
            return
        except AgentEngineError as e:
            logger.error("chat: agent %s rejected the turn: %s", agent_id, e)
            detail = (
                f"The agent rejected the request ({e.status})."
                if e.status else f"Could not reach the agent ({e})."
            )
            yield sse("failed", {"detail": detail})
            return

        for event, data in _iter_stream_frames(response, fallback_session_id=session_id):
            if event in ("done", "failed"):
                saw_terminal = True
            yield sse(event, data)

    except Exception as e:  # noqa: BLE001
        # Covers a dropped connection and the read timeout.
        logger.error("chat: agent %s turn failed: %s", agent_id, e)
        yield sse("failed", {"detail": f"Could not reach the agent ({type(e).__name__})."})
        return
    finally:
        if response is not None:
            response.close()

    if not saw_terminal:
        # The upstream stream ended without a `done` frame. Close ours anyway, or the browser
        # waits on a reply that is never coming.
        logger.warning("chat: agent %s stream ended with no terminal frame", agent_id)
        yield sse("done", {"sessionId": session_id})
