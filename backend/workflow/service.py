"""Start an authorization case, and report what a running one looks like."""

import logging
from datetime import date

from db.mdb import MongoDBConnector
from members.service import MemberService
from audit.repository import AuditRepository

from .agent_invoker import AgentInvoker, INSURANCE_AGENT, CARE_AGENT

logger = logging.getLogger(__name__)

# Trace states that mean a case is still live on the member's record: an agent is
# working it, or a medical director owes it a decision.
_OPEN_TRACE_STATUSES = ("open", "in_progress", "pending", "pending_review")

# What the case needs next. Derived from the trace on every pass rather than tracked
# in a variable, so the chain stays correct even if a presenter drove part of the run
# by hand in the playground.
NEEDS_START = "start"                          # no trace yet — Insurance, Steps 0-2
NEEDS_CLINICAL_REVIEW = "clinical_review"      # gates passed — Healthcare, Steps 3-7
NEEDS_ROUTING = "routing"                      # recommendation exists — Insurance, 8-9
AWAITING_MEDICAL_DIRECTOR = "awaiting_medical_director"   # stop: a human owes a decision
DONE = "done"                                  # stop: closed
STALLED = "stalled"                            # stop: an agent produced nothing new

# A full run is three agent turns (insurance, healthcare, insurance). The cap is a
# little higher to tolerate one retry, and exists so a misbehaving agent cannot spin
# this loop forever.
_MAX_TURNS = 4


class AuthorizationWorkflowService:
    """The frontend's entry point into the prior-authorization workflow.

    Deliberately thin. Step 0 (flip the pending action, open the claim, open the
    trace) belongs to the Insurance Agent, so this service reads the member, decides
    whether a case *may* be started, composes the agent's opening message and hands
    it off. It writes nothing to the member, the claim or the trace — two writers on
    one workflow is how a demo ends up with orphaned claims.
    """

    def __init__(self, connector: MongoDBConnector, invoker: AgentInvoker = None):
        self._connector = connector
        self.members = MemberService(connector)
        self.traces = AuditRepository(connector)
        self.invoker = invoker or AgentInvoker()

    # --- reads ----------------------------------------------------------------

    def _open_trace(self, member_id: str) -> dict:
        """The member's most recent unfinished trace, if any."""
        traces = self.traces.find_by_member(member_id) or []
        open_traces = [
            t
            for t in traces
            if (t.get("status") or "").strip().lower() in _OPEN_TRACE_STATUSES
            or not ((t.get("review") or {}).get("closedBy"))
        ]
        if not open_traces:
            return None
        open_traces.sort(key=lambda t: t.get("createdAt") or "", reverse=True)
        return open_traces[0]

    # --- start ----------------------------------------------------------------

    def check_can_start(self, member_id: str) -> dict:
        """Decide whether "Start Process" may fire, without side effects.

        Returns `{"can_start": bool, ...}`. Split out from `start` so the route can
        answer 404/409 before scheduling anything, and so the frontend can grey the
        button out without attempting the call.
        """
        case = self.members.get_open_case(member_id)
        if case is None:
            return {"can_start": False, "reason": "member_not_found", "member_id": member_id}

        # An already-open trace is the strongest signal: the agent has begun Step 0,
        # whatever the pending action currently says.
        open_trace = self._open_trace(member_id)
        if open_trace:
            return {
                "can_start": False,
                "reason": "already_in_progress",
                "member_id": member_id,
                "trace_id": open_trace.get("traceId"),
                "trace_status": open_trace.get("status"),
                "detail": (
                    f"Member {member_id} already has an open case on trace "
                    f"{open_trace.get('traceId')} (status "
                    f"{open_trace.get('status') or 'unknown'}). Watch that trace instead "
                    "of starting a second one."
                ),
            }

        if not case.get("has_open_case"):
            return {
                "can_start": False,
                "reason": "no_pending_action",
                "member_id": member_id,
                "detail": case.get("detail"),
            }

        if (case.get("status") or "") != "pending":
            return {
                "can_start": False,
                "reason": "already_in_progress",
                "member_id": member_id,
                "trace_id": case.get("trace_id"),
                "detail": case.get("detail"),
            }

        return {"can_start": True, "member_id": member_id, "case": case}

    # --- what does the case need next? ---------------------------------------

    def _live_trace(self, member_id: str) -> dict:
        """The trace for the request currently being worked, or None.

        Found through the member's open pending action, which Step 0 stamps with
        `linkedAuditTraceId` — the request's own trace, rather than whichever trace
        happens to be newest. A member with years of history still resolves correctly.
        """
        case = self.members.get_open_case(member_id) or {}
        trace_id = case.get("trace_id")
        if not trace_id:
            return None
        return self.traces.get_by_key(trace_id)

    def _resolve_trace_id(self, member_id: str) -> str:
        """The trace of the case just worked, however far it got.

        Normally the open pending action names it. But a case can be opened and closed
        inside a single agent turn — an eligibility lapse or a benefit exclusion, where
        Step 9 resolves the action immediately — and then there is no open action left
        to read. Falling back to the member's newest trace covers that: within one run,
        the newest trace is the one this run created.
        """
        trace = self._live_trace(member_id)
        if trace:
            return trace.get("traceId")

        traces = self.traces.find_by_member(member_id) or []
        if not traces:
            return None
        return max(traces, key=lambda t: t.get("createdAt") or "").get("traceId")

    def next_action(self, member_id: str, trace_id: str = None) -> str:
        """Read the record and say what the case needs next.

        Every branch is a read of state the agents wrote themselves. Order matters:
        closure and human routing are checked before anything else, because a closed
        case must never be pushed further — that is what stops Grace (benefit
        exclusion) and Frank (ineligible) after a single turn, and what keeps David
        and Aisha parked with their medical director instead of being auto-resolved.

        Pass `trace_id` once the run knows it. Without it the trace is discovered
        through the member's OPEN pending action — which closure resolves, so a
        finished case would otherwise read as "no case at all" and be mistaken for one
        that needs starting.
        """
        trace = self.traces.get_by_key(trace_id) if trace_id else self._live_trace(member_id)
        if not trace:
            return NEEDS_START

        review = trace.get("review") or {}
        if review.get("closedBy"):
            return DONE
        if review.get("routedToHuman"):
            return AWAITING_MEDICAL_DIRECTOR

        # A recommendation on the trace means clinical review finished; Step 8 routing
        # and Step 9 closure are the Insurance Agent's again.
        if (trace.get("outcome") or {}).get("decision"):
            return NEEDS_ROUTING

        step_names = {s.get("name") for s in (trace.get("steps") or [])}
        if "coverage_gate" in step_names:
            return NEEDS_CLINICAL_REVIEW

        # Trace exists but the administrative gates have not both landed. The
        # Insurance Agent is either still working or it stopped early; either way this
        # chain has nothing useful to add.
        return STALLED

    # --- messages -------------------------------------------------------------

    def compose_agent_message(self, case: dict, service_date: str) -> str:
        """The opening message handed to the Insurance Agent.

        States the member and the service date and nothing else of substance. It
        deliberately does not restate the workflow: the agent's system prompt owns
        PHASE A, and a message that re-specifies the steps would compete with it. The
        proposed therapy is named only so the run is legible in the playground —
        the agent still reads it off `pendingActions[]` itself.
        """
        return (
            f"Start the prior authorization process for member {case['member_id']}. "
            f"The date of service is {service_date}. "
            f"The member clicked Start Process on pending action {case['action_id']} "
            f"({case.get('proposed_treatment') or 'therapy unspecified'}). "
            "Begin at PHASE A, Step 0."
        )

    @staticmethod
    def compose_clinical_review_message(member_id: str) -> str:
        """Hand the case to the Care-Coordination Agent (Steps 3-7).

        Carries only the member id: the agent calls `get_open_case(member_id)` to find
        the trace itself, which is what that tool exists for. Passing a trace id here
        would be this service asserting something the agent can read first-hand.
        """
        return (
            f"Run the clinical assessment for member {member_id}. The administrative "
            "gates are already recorded on the open case. Work Steps 3 through 7 and "
            "record your recommendation on the case's trace."
        )

    @staticmethod
    def compose_routing_message(member_id: str) -> str:
        """Resume the Insurance Agent at PHASE B (Steps 8-9)."""
        return (
            f"Continue the prior authorization process for member {member_id}. A "
            "clinical recommendation is now on the open case. Resume at PHASE B: route "
            "the decision, then close it or escalate it as the routing check directs."
        )

    # --- the run --------------------------------------------------------------

    def orchestrate(self, member_id: str, opening_message: str, publish=None) -> list:
        """Drive the case to a stopping point, one agent turn at a time.

        `/invoke` blocks until an agent's turn is complete, so this is plain sequential
        code: invoke, re-read the record, decide, invoke again. Three turns in the
        normal case — insurance, healthcare, insurance.

        Runs in a background task, never in a request. Returns the turns it took, for
        the log and for tests.

        Two rules keep it honest:
          * the decision to continue comes from `next_action`, i.e. from what the
            agents wrote — never from an assumption about what should have happened
          * a failed turn stops the chain, because invoking the next agent on top of a
            half-finished case makes the failure harder to see, not easier

        `publish(event, data)` is optional and mirrors the turn structure to a live
        viewer. It carries the handoffs, which is what fills the 10-20 second silences
        while an LLM works and no step has been recorded yet. A run with no viewer
        passes None and behaves identically.
        """
        emit = publish or (lambda event, data=None: None)
        turns = []
        # Learned from the member's pending action after the first turn, then held: the
        # case's identity for the rest of the run, so closure cannot make it vanish.
        trace_id = None

        for turn in range(_MAX_TURNS):
            action = self.next_action(member_id, trace_id=trace_id)

            if action in (DONE, AWAITING_MEDICAL_DIRECTOR, STALLED):
                logger.warning("case for %s stops: %s", member_id, action)
                turns.append({"action": action, "invoked": None})
                emit("stopped", {"reason": action, "trace_id": trace_id, "turns": len(turns) - 1})
                break

            if action == NEEDS_START:
                agent, message = INSURANCE_AGENT, opening_message
            elif action == NEEDS_CLINICAL_REVIEW:
                agent, message = CARE_AGENT, self.compose_clinical_review_message(member_id)
            elif action == NEEDS_ROUTING:
                agent, message = INSURANCE_AGENT, self.compose_routing_message(member_id)
            else:
                logger.error("unrecognised next action %r for %s", action, member_id)
                emit("error", {"detail": f"unrecognised next action {action!r}"})
                break

            logger.warning(
                "case for %s turn %d: %s -> %s agent", member_id, turn + 1, action, agent
            )
            emit("turn_started", {"turn": turn + 1, "action": action, "agent": agent})
            result = self.invoker.invoke(agent, message)
            turns.append({"action": action, "invoked": agent, "ok": result.get("ok")})

            if not result.get("ok"):
                logger.error(
                    "case for %s stopped: %s agent failed (%s)",
                    member_id,
                    agent,
                    result.get("error"),
                )
                emit("error", {"agent": agent, "detail": result.get("error")})
                break

            if trace_id is None:
                trace_id = self._resolve_trace_id(member_id)
            emit("turn_finished", {"turn": turn + 1, "agent": agent, "trace_id": trace_id})

            # An agent that returned successfully without moving the case forward would
            # otherwise have this loop re-issue the same instruction until the cap.
            if self.next_action(member_id, trace_id=trace_id) == action:
                logger.error(
                    "case for %s stopped: %s agent finished but the case still needs "
                    "%s — nothing was recorded on the trace",
                    member_id,
                    agent,
                    action,
                )
                emit("error", {
                    "agent": agent,
                    "detail": (
                        f"the {agent} agent finished but recorded nothing, so the case "
                        f"still needs {action}"
                    ),
                })
                break
        else:
            logger.error(
                "case for %s hit the %d-turn cap without reaching a stopping point",
                member_id,
                _MAX_TURNS,
            )
            emit("error", {"detail": f"stopped after the {_MAX_TURNS}-turn cap"})

        return turns

    def start(self, member_id: str, service_date: str = None) -> dict:
        """Prepare an authorization run and return the handle immediately.

        Returns the payload plus a `run` callable the route schedules as a background
        task. Nothing is invoked here — this method stays synchronous and fast so the
        endpoint can answer the button press in milliseconds.

        `trace_id` and `claim_id` are absent by design: the agent mints them during
        Step 0, so the frontend discovers them by watching the member.
        """
        gate = self.check_can_start(member_id)
        if not gate.get("can_start"):
            return gate

        case = gate["case"]
        as_of = service_date or date.today().isoformat()
        message = self.compose_agent_message(case, as_of)
        target = self.invoker.describe(INSURANCE_AGENT)

        def run(publish=None):
            self.orchestrate(member_id, message, publish=publish)

        return {
            "can_start": True,
            "status": "starting",
            "member_id": member_id,
            "action_id": case["action_id"],
            "proposed_treatment": case.get("proposed_treatment"),
            "related_diagnosis_code": case.get("related_diagnosis_code"),
            "raised_by": case.get("raised_by"),
            "service_date": as_of,
            "agent": target,
            "agent_message": message,
            # Null until the agent's Step 0 writes them. The frontend watches the
            # member for a trace to appear rather than expecting them here.
            "trace_id": None,
            "claim_id": None,
            "detail": (
                f"Case started for {member_id} in {target['mode']} mode. The backend "
                "drives the agents in turn — administrative gates, clinical review if "
                "the case gets that far, then routing and closure — stopping when the "
                "case closes or a medical director is required."
            ),
            "run": run,
        }
