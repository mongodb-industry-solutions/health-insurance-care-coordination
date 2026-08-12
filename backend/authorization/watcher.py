"""Turn writes to the audit log into progress events, using a MongoDB change stream.

The agents do not report to the backend — they write their reasoning to the trace and
move on. So the way to know what a run is doing is to watch the document it is
writing. Every step, recommendation, escalation and closure reaches the browser
because it landed in MongoDB first, which is also the property the demo is about: the
audit trail is the live workflow state, not a log written beside it.

Goes through `AuditRepository` rather than naming a collection, so the trace store
stays defined in one place (`shared/collections.py`).

Requires a replica set (any Atlas cluster). Against a standalone mongod, `watch()`
raises and this falls back to polling the same document with the same diff logic, so
the events the client sees are identical either way.
"""

import logging
import threading
import time

from db.mdb import MongoDBConnector
from audit.repository import AuditRepository

from .events import EventBus

logger = logging.getLogger(__name__)

# How long `try_next()` waits for a change before returning None, letting the loop
# re-check whether it has been asked to stop.
_AWAIT_MS = 1000
# Poll interval for the fallback path.
_POLL_SECONDS = 1.0


class TraceWatcher:
    """Publishes one member's trace activity to the bus until asked to stop.

    Runs on its own thread: pymongo is synchronous, and a change stream is a blocking
    cursor. The bus handles the hop back to the event loop.
    """

    def __init__(self, connector: MongoDBConnector, bus: EventBus, member_id: str):
        self.repository = AuditRepository(connector)
        self.bus = bus
        self.member_id = member_id
        self._stop = threading.Event()
        self._thread = None
        # Everything already reported, so a resumed watch or a repeated change on the
        # same document cannot replay events the client has seen.
        self._seen_trace = None
        self._seen_steps = 0
        self._seen_decision = None
        self._seen_escalated = False
        self._seen_closed = False

    # --- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name=f"trace-watch-{self.member_id}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # --- publishing -----------------------------------------------------------

    def _emit(self, event: str, data: dict) -> None:
        self.bus.publish(self.member_id, event, data)

    def _report(self, trace: dict) -> None:
        """Publish whatever is new in this version of the trace.

        Diffed against what has already been sent rather than derived from the change
        event itself, because one update can add a step *and* set the outcome, and
        because a change stream may deliver the same change more than once.
        """
        if not trace:
            return

        trace_id = trace.get("traceId")
        if trace_id and trace_id != self._seen_trace:
            self._seen_trace = trace_id
            # A different trace is a different case: its steps start at 1 again and it
            # has its own decision and closure. Carrying the previous trace's cursors
            # over would silently swallow the first N steps of this one.
            self._seen_steps = 0
            self._seen_decision = None
            self._seen_escalated = False
            self._seen_closed = False
            # The first thing the frontend learns that it could not know from `start`.
            self._emit("trace_opened", {
                "trace_id": trace_id,
                "member_id": self.member_id,
                "status": trace.get("status"),
            })

        steps = trace.get("steps") or []
        for step in steps[self._seen_steps:]:
            self._emit("step", {
                "trace_id": trace_id,
                "step_id": step.get("stepId"),
                "name": step.get("name"),
                "memory_type": step.get("memoryType"),
                # Which agent wrote it, straight off the record — so the UI does not
                # have to infer it from the last turn_started it happened to see.
                "recorded_by": step.get("recordedBy"),
                "confidence": step.get("confidence"),
                "detail": step.get("detail"),
            })
        self._seen_steps = len(steps)

        outcome = trace.get("outcome") or {}
        decision = outcome.get("decision")
        if decision and decision != self._seen_decision:
            self._seen_decision = decision
            self._emit("recommendation", {
                "trace_id": trace_id,
                "decision": decision,
                "confidence": outcome.get("confidence"),
                "rationale": outcome.get("rationale"),
            })

        review = trace.get("review") or {}
        if review.get("routedToHuman") and not self._seen_escalated:
            self._seen_escalated = True
            self._emit("escalated", {
                "trace_id": trace_id,
                "reason": (trace.get("audit") or {}).get("reviewRequiredReason"),
                "final_decision_maker": review.get("finalDecisionMaker"),
                "case_brief": review.get("caseBrief"),
            })

        if review.get("closedBy") and not self._seen_closed:
            self._seen_closed = True
            self._emit("closed", {
                "trace_id": trace_id,
                "status": trace.get("status"),
                "decision": decision,
                "closed_by": review.get("closedBy"),
            })

    # --- sources --------------------------------------------------------------

    def _run(self) -> None:
        try:
            self._watch()
        except Exception as e:
            # Standalone mongod, a missing privilege, a dropped connection: the client
            # should keep getting events, so degrade to polling rather than going quiet.
            logger.warning(
                "change stream unavailable for %s (%s); falling back to polling",
                self.member_id,
                e,
            )
            self._poll()

    def _watch(self) -> None:
        pipeline = [{"$match": {"fullDocument.subjectRef": self.member_id}}]
        with self.repository.collection.watch(
            pipeline,
            full_document="updateLookup",
            max_await_time_ms=_AWAIT_MS,
        ) as stream:
            # The trace may already exist and carry steps — a reconnect, or a first turn
            # that beat the watcher. Report that state before waiting on changes.
            self._report(self._current_trace())
            while not self._stop.is_set():
                change = stream.try_next()
                if change is None:
                    continue          # timed out waiting; loop back and re-check _stop
                self._report(change.get("fullDocument"))

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                self._report(self._current_trace())
            except Exception as e:
                logger.error("polling the trace for %s failed: %s", self.member_id, e)
            time.sleep(_POLL_SECONDS)

    def _current_trace(self) -> dict:
        """The member's newest trace, whatever state it is in."""
        traces = self.repository.find_by_member(self.member_id) or []
        if not traces:
            return None
        return max(traces, key=lambda t: t.get("createdAt") or "")
