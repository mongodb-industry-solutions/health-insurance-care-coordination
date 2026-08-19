"""Chat transport: one user message in, a stream of SSE frames out.

Why this lives in the backend rather than the browser calling an agent directly:

  * the agent playgrounds send no CORS headers, so a browser fetch is blocked;
  * it keeps *one* definition of the agent transport, shared with the authorization
    workflow, so the cloud migration has a single seam to cut (see
    CLOUD-AGENT-MIGRATION.md);
  * when the cloud transport lands it carries an API key, which must never reach the
    browser. Putting the proxy here now means that change is invisible to the frontend.

The upstream frame shape is the Orchestration Engine's (`chunk_type`-tagged JSON on
`data:` lines). This module translates it into the `event:`/`data:` framing the frontend
already parses for the authorization run, so the browser has exactly one SSE dialect to
understand.

Everything here is deliberately synchronous. FastAPI iterates a sync generator passed to
`StreamingResponse` on its threadpool, so blocking reads never touch the event loop —
the same rule `agent_invoker.py` follows, and it avoids adding an async HTTP dependency.
"""

import json
import logging
import re
import urllib.error
import urllib.request

from . import agents

logger = logging.getLogger(__name__)

# A chat turn is a single question, not a whole prior-auth run, so this is far shorter
# than the workflow's 900s. Long enough for a slow tool call, short enough that a wedged
# agent surfaces as an error instead of a spinner that never resolves.
_TIMEOUT_SECONDS = 180

_SSE_DATA_PREFIX = "data: "
_SSE_DONE_SENTINEL = "[DONE]"

# agent id -> whether `/invokeStream` exists, learned on the first turn. Assumed true
# until proven otherwise, so a platform that *does* stream is never needlessly downgraded.
_supports_streaming: dict[str, bool] = {}


def sse(event: str, data: dict) -> str:
    """One SSE frame. The blank line terminates it — without it the browser buffers."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _post(url: str, payload: dict, extra_headers: dict | None = None):
    """Open a POST and hand back the live response object (not the body).

    `extra_headers` carries the bearer token in platform mode (see `agents.target()`);
    empty in local mode, so this stays the same plain call either way.
    """
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS)


def _translate(parsed: dict) -> tuple[str, dict] | None:
    """One upstream `chunk_type` frame → one of our SSE events, or None to ignore.

    Unknown chunk types are dropped rather than forwarded: the Orchestration Engine adds
    new ones over time and an unrecognised frame is never worth showing to a member.
    """
    kind = parsed.get("chunk_type")

    if kind == "text":
        content = parsed.get("content") or ""
        return ("token", {"content": content}) if content else None

    if kind == "progress":
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
        # `execution_id` doubles as the conversation handle — there is no separate
        # session concept upstream. The browser stores the *first* one it sees and
        # sends it back on later turns; see useChat.js.
        return "done", {"sessionId": parsed.get("execution_id")}

    return None


def _readable_error(raw) -> str:
    """Upstream provider errors arrive as Python-repr strings rather than JSON
    (e.g. `Error code: 400 - {'error': {'message': "...", ...}}`). Pull out the human
    half when the shape matches, and fall back to the raw text when it does not."""
    if not isinstance(raw, str):
        return str(raw)

    match = re.search(r"'message':\s*\"([^\"]*)\"", raw)
    return match.group(1) if match else raw


def _iter_stream_frames(response):
    """Yield translated events from a live SSE response.

    Reads line-wise off the socket so tokens reach the browser as they are produced;
    `response` is a file-like object, and iterating it blocks per line rather than
    buffering the whole body.
    """
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

        translated = _translate(parsed)
        if translated:
            yield translated


def _non_streaming_turn(agent_id: str, payload: dict):
    """Fallback for an engine build without `/invokeStream`: take the whole reply at
    once and emit it as a single token, so the UI contract is identical either way."""
    target = agents.target(agent_id)
    url = f"{target['base_url']}/invoke"
    logger.info("chat: falling back to non-streaming %s", url)

    with _post(url, payload, target["headers"]) as response:
        raw = response.read().decode("utf-8", errors="replace")

    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        yield "token", {"content": raw}
        yield "done", {"sessionId": None}
        return

    # The engine has used a few different field names for the answer across versions.
    text = (
        body.get("response")
        or body.get("content")
        or body.get("message")
        or body.get("result")
        or ""
    )
    if isinstance(text, dict):
        text = text.get("content") or json.dumps(text)

    if text:
        yield "token", {"content": str(text)}
    yield "done", {"sessionId": body.get("execution_id") or body.get("session_id")}


def stream_turn(agent_id: str, message: str, session_id: str | None = None):
    """Drive one chat turn and yield ready-to-send SSE frames.

    Never raises: a failed turn has to arrive as a `failed` event on an already-open
    stream, because the response headers went out long before the agent answered. The
    stream always ends on `done` or `failed`, which is what lets the browser stop
    reading.
    """
    payload = {"message": message}
    # Omitted entirely rather than sent as null — "absent" is how the engine is told to
    # start a new conversation.
    if session_id:
        payload["session_id"] = session_id

    yield sse("accepted", {"agent": agent_id})

    saw_terminal = False
    try:
        # Inside the try: a missing platform credential must arrive as a `failed`
        # event too, not an exception escaping the generator after headers are sent.
        try:
            target = agents.target(agent_id)
        except RuntimeError as e:
            logger.error("chat: agent %s misconfigured: %s", agent_id, e)
            yield sse("failed", {"detail": str(e)})
            return
        response = None
        if _supports_streaming.get(agent_id, True):
            try:
                response = _post(f"{target['base_url']}/invokeStream", payload, target["headers"])
                frames = _iter_stream_frames(response)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                # This engine build has no streaming endpoint — true of the local
                # playground today. Remembered so every later turn skips straight to
                # `/invoke` instead of paying for a 404 first.
                logger.info("chat: %s has no /invokeStream; using /invoke", agent_id)
                _supports_streaming[agent_id] = False

        if response is None:
            frames = _non_streaming_turn(agent_id, payload)

        try:
            for event, data in frames:
                if event in ("done", "failed"):
                    saw_terminal = True
                yield sse(event, data)
        finally:
            if response is not None:
                response.close()

    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        logger.error("chat: agent %s rejected the turn: %s %s", agent_id, e.code, detail)
        yield sse("failed", {"detail": f"The agent rejected the request ({e.code})."})
        return
    except Exception as e:
        # Covers a stack that is not listening and the read timeout.
        logger.error("chat: agent %s turn failed: %s", agent_id, e)
        yield sse("failed", {"detail": f"Could not reach the agent ({type(e).__name__})."})
        return

    if not saw_terminal:
        # The upstream stream ended without a `done` frame. Close ours anyway, or the
        # browser waits on a reply that is never coming.
        logger.warning("chat: agent %s stream ended with no terminal frame", agent_id)
        yield sse("done", {"sessionId": None})
