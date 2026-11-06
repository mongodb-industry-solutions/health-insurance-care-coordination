"""In-process pub/sub for streaming a case's progress to the browser.

One topic per member. A run publishes; each open SSE connection subscribes. Nobody
listening is a normal state — a case started from curl still runs to completion, its
events simply go nowhere.

IN-MEMORY AND SINGLE-PROCESS ON PURPOSE. This is a presenter-driven demo on one
uvicorn worker. Run more than one worker and a viewer connected to worker B sees
nothing from a run executing on worker A; the fix then is Redis pub/sub or tailing
the trace directly, not a bigger dict.
"""

import asyncio
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Publishers run in worker threads (the agent calls block), so every subscription
# remembers the loop its queue belongs to and hands work back to it.
_QUEUE_MAX = 200

# After one of these, a stream closes: the case has reached a stopping point, or the
# run failed. Anything else is progress.
TERMINAL_EVENTS = ("stopped", "error")


class EventBus:
    def __init__(self):
        self._topics: dict[str, set[tuple[asyncio.Queue, asyncio.AbstractEventLoop]]] = {}

    def subscribe(self, topic: str) -> asyncio.Queue:
        """Register a listener. Call from the event loop that will read the queue."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        loop = asyncio.get_running_loop()
        self._topics.setdefault(topic, set()).add((queue, loop))
        return queue

    def unsubscribe(self, topic: str, queue: asyncio.Queue) -> None:
        subscribers = self._topics.get(topic) or set()
        for entry in list(subscribers):
            if entry[0] is queue:
                subscribers.discard(entry)
        if not subscribers:
            self._topics.pop(topic, None)

    def listener_count(self, topic: str) -> int:
        return len(self._topics.get(topic) or ())

    def publish(self, topic: str, event: str, data: dict = None) -> None:
        """Fan an event out to every listener on `topic`.

        Safe to call from any thread. Never raises and never blocks the caller: a
        publish that fails must not take down an agent run that is otherwise fine.
        """
        payload = {"event": event, "data": data or {}}
        for queue, loop in list(self._topics.get(topic) or ()):
            try:
                loop.call_soon_threadsafe(self._offer, queue, payload)
            except RuntimeError:
                # Loop already closed — the listener is gone but did not unsubscribe.
                self.unsubscribe(topic, queue)

    @staticmethod
    def _offer(queue: asyncio.Queue, payload: dict) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            # A reader this far behind is not going to catch up usefully. Dropping is
            # better than blocking the loop or growing without bound.
            logger.warning("dropping progress event %r: listener queue full", payload.get("event"))


def sse(event: str, data: dict) -> str:
    """One Server-Sent Event frame.

    The blank line terminates the frame — without it the browser buffers forever.
    """
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def keepalive() -> str:
    """An SSE comment. Keeps the connection alive through the long LLM pauses
    between steps, where nothing is published for 20 seconds at a time."""
    return ": keepalive\n\n"


# One bus per process, shared by the routes and the orchestrator.
_bus: Optional[EventBus] = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
