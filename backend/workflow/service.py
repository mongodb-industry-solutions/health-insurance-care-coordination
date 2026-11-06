"""Start an authorization case, and report what a running one looks like."""

import logging
import os
import time
from datetime import date

from clinical.profiles.service import ProfileService
from db.mdb import MongoDBConnector
from insurance.members.service import MemberService
from traces.repository import TraceRepository
from traces.stages import (
    STAGE_ADMIN_CLEARED,
    STAGE_CLINICAL_RECOMMENDED,
    STAGE_CLOSED,
    STAGE_ESCALATED,
    STAGE_ROUTED,
)

from .agent_invoker import AgentInvoker, INSURANCE_AGENT, CARE_AGENT
from .clinical_sync import ClinicalSync

logger = logging.getLogger(__name__)

# What the case needs next. Derived from the trace's `workflow.stage` on every pass rather
# than tracked in a variable, so the chain stays correct even if a presenter drove part of
# the run by hand in the playground.
NEEDS_START = "start"                          # no trace yet — Insurance, Steps 0-2
NEEDS_CLINICAL_REVIEW = "clinical_review"      # gates cleared — Care, Steps 3-7
NEEDS_ROUTING = "routing"                      # recommendation exists — Insurance, 8-9
AWAITING_MEDICAL_DIRECTOR = "awaiting_medical_director"   # stop: a human owes a decision
DONE = "done"                                  # stop: closed
STALLED = "stalled"                            # stop: an agent produced nothing new

# A full run is three agent turns (insurance, care, insurance). The cap is a little higher
# to tolerate one retry, and exists so a misbehaving agent cannot spin this loop forever.
_MAX_TURNS = 4

# When a turn times out (the platform's `AGENT_TIMEOUT`, or our own read timeout), the agent
# may still be running and may well finish: the platform does not cancel it. So instead of
# giving up, the orchestrator keeps reading the trace for this long, and carries on if the
# agent's work lands. 0 turns that off (a timeout is then an immediate failure).
_DEFAULT_GRACE_SECONDS = 600.0
_DEFAULT_GRACE_POLL_SECONDS = 5.0


class AuthorizationWorkflowService:
    """The frontend's entry point into the prior-authorization workflow.

    Starts a case and drives the agents in turn, reading every decision off
    `workflow.stage`. The agents write the trace; this service writes only the clinical
    record (through `ClinicalSync`): the action is flipped to `in_progress` at start, linked
    to the trace once it exists, and resolved when the case closes. It is the one component
    that holds both databases, so it also composes the Insurance Agent's opening message
    from the clinical order the agent cannot see.
    """

    def __init__(
        self,
        insurance: MongoDBConnector,
        clinical: MongoDBConnector,
        invoker: AgentInvoker = None,
        grace_seconds: float = None,
        poll_seconds: float = None,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.members = MemberService(insurance)
        self.traces = TraceRepository(insurance)
        self.profiles = ProfileService(clinical)
        self.sync = ClinicalSync(self.profiles)
        self.invoker = invoker or AgentInvoker()
        # AGENT_TURN_GRACE_SECONDS / AGENT_GRACE_POLL_SECONDS: see `_await_turn`.
        self.grace_seconds = float(
            grace_seconds if grace_seconds is not None
            else os.getenv("AGENT_TURN_GRACE_SECONDS") or _DEFAULT_GRACE_SECONDS
        )
        self.poll_seconds = float(
            poll_seconds if poll_seconds is not None
            else os.getenv("AGENT_GRACE_POLL_SECONDS") or _DEFAULT_GRACE_POLL_SECONDS
        )
        self._sleep = sleep
        self._clock = clock

    # --- reads ----------------------------------------------------------------

    def _open_trace(self, member_id: str) -> dict:
        """The member's most recent unfinished trace, if any."""
        traces = self.traces.find_by_subject(member_id) or []
        open_traces = [
            t
            for t in traces
            if not (t.get("review") or {}).get("closedBy")
            and (t.get("workflow") or {}).get("stage") != STAGE_CLOSED
        ]
        if not open_traces:
            return None
        open_traces.sort(key=lambda t: t.get("createdAt") or "", reverse=True)
        return open_traces[0]

    # --- start ----------------------------------------------------------------

    def _case(self, member_id: str, action: dict, profile: dict) -> dict:
        """The facts the Insurance Agent needs, which only the clinical record holds."""
        code = action.get("relatedDiagnosisCode")
        provider = ((profile.get("current_care_plan") or {}).get("managing_provider")) or {}
        return {
            "member_id": member_id,
            "action_id": action.get("actionId"),
            "type": action.get("type"),
            "status": action.get("status"),
            "proposed_treatment": action.get("proposedTreatment"),
            "related_diagnosis_code": code,
            "diagnosis_display": self.profiles.diagnosis_display(profile, code),
            "raised_by": action.get("raisedBy"),
            "raised_at": action.get("raisedAt"),
            "provider_id": provider.get("providerId"),
            "provider_name": provider.get("name") or action.get("raisedBy"),
            "provider_specialty": provider.get("specialty"),
            "trace_id": action.get("linkedAuditTraceId"),
        }

    def check_can_start(self, member_id: str) -> dict:
        """Decide whether "Start Process" may fire, without side effects.

        Returns `{"can_start": bool, ...}`. Split out from `start` so the route can answer
        404/409 before scheduling anything, and so the frontend can grey the button out
        without attempting the call.
        """
        if not self.members.get_member(member_id):
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
                    f"{open_trace.get('traceId')} (stage "
                    f"{(open_trace.get('workflow') or {}).get('stage') or 'unknown'}). Watch "
                    "that trace instead of starting a second one."
                ),
            }

        profile = self.profiles.get_profile(member_id)
        if profile is None:
            return {
                "can_start": False,
                "reason": "no_pending_action",
                "member_id": member_id,
                "detail": f"Member {member_id} has no clinical profile, so there is no order to start.",
            }

        action = self.profiles.get_action(member_id)
        if action is None:
            return {
                "can_start": False,
                "reason": "no_pending_action",
                "member_id": member_id,
                "detail": f"Member {member_id} has no open pending action.",
            }

        case = self._case(member_id, action, profile)
        if (case.get("status") or "") != "pending":
            return {
                "can_start": False,
                "reason": "already_in_progress",
                "member_id": member_id,
                "trace_id": case.get("trace_id"),
                "detail": (
                    f"Action {case['action_id']} is {case['status']}: a case is already "
                    "under way for it."
                ),
            }

        # The Insurance Agent reads nothing from the clinical side, so the message has to
        # carry what it needs. Refuse here, naming what is missing, rather than start a run
        # that fails at Step 0 for want of a diagnosis or a provider.
        missing = [
            label
            for label, value in (
                ("therapy", case["proposed_treatment"]),
                ("diagnosis code", case["related_diagnosis_code"]),
                ("referring provider id", case["provider_id"]),
            )
            if not value
        ]
        if missing:
            return {
                "can_start": False,
                "reason": "incomplete_order",
                "member_id": member_id,
                "detail": (
                    f"The physician's order for action {case['action_id']} is missing: "
                    f"{', '.join(missing)}. The Insurance Agent cannot open the case without it."
                ),
            }

        return {"can_start": True, "member_id": member_id, "case": case}

    # --- what does the case need next? ---------------------------------------

    def _live_trace(self, member_id: str) -> dict:
        """The member's unfinished trace, or None."""
        return self._open_trace(member_id)

    def _trace_for_action(self, member_id: str, action_id: str) -> dict:
        """The newest trace opened for this physician's order, finished or not."""
        traces = [
            t for t in self.traces.find_by_subject(member_id) or []
            if (t.get("request") or {}).get("actionId") == action_id
        ]
        return max(traces, key=lambda t: t.get("createdAt") or "") if traces else None

    def _resolve_trace_id(self, member_id: str, action_id: str = None) -> str:
        """The trace of the case just worked, however far it got.

        A case can be opened and closed inside a single agent turn (an eligibility lapse or
        a benefit exclusion), and then no unfinished trace is left to read. With the action
        id the run finds its own trace exactly, so a member's older traces are never
        mistaken for it. Without one it falls back to the unfinished trace, then the newest.
        """
        if action_id:
            trace = self._trace_for_action(member_id, action_id)
            return trace.get("traceId") if trace else None

        trace = self._live_trace(member_id)
        if trace:
            return trace.get("traceId")

        traces = self.traces.find_by_subject(member_id) or []
        if not traces:
            return None
        return max(traces, key=lambda t: t.get("createdAt") or "").get("traceId")

    def next_action(self, member_id: str, trace_id: str = None) -> str:
        """Read the record and say what the case needs next, from `workflow.stage`.

        | stage                  | next action                                                 |
        |------------------------|-------------------------------------------------------------|
        | no trace               | start                                                       |
        | OPENED                 | stalled (the gates were not cleared)                        |
        | ADMIN_CLEARED          | clinical_review                                             |
        | CLINICAL_RECOMMENDED   | routing                                                     |
        | ROUTED                 | routing (the Insurance Agent still has to close or escalate) |
        | ESCALATED              | awaiting_medical_director                                   |
        | CLOSED                 | done                                                        |

        ROUTED maps to routing whichever way the verdict went: only the escalation sets
        `review.routedToHuman`, which is what puts a case in the director's queue, so a case
        parked at ROUTED would be invisible to everyone.

        Closure and human routing are checked before anything else, because a closed case
        must never be pushed further. Pass `trace_id` once the run knows it; without it the
        trace is discovered as the member's unfinished one, which closure removes.
        """
        trace = self.traces.get_by_key(trace_id) if trace_id else self._live_trace(member_id)
        if not trace:
            return NEEDS_START

        review = trace.get("review") or {}
        stage = (trace.get("workflow") or {}).get("stage")
        if stage == STAGE_CLOSED or review.get("closedBy"):
            return DONE
        if stage == STAGE_ESCALATED or review.get("routedToHuman"):
            return AWAITING_MEDICAL_DIRECTOR
        if stage == STAGE_ADMIN_CLEARED:
            return NEEDS_CLINICAL_REVIEW
        if stage in (STAGE_CLINICAL_RECOMMENDED, STAGE_ROUTED):
            return NEEDS_ROUTING
        # OPENED, or a trace with no workflow at all: the Insurance Agent is either still
        # working or it stopped early; either way this chain has nothing useful to add.
        return STALLED

    # --- messages -------------------------------------------------------------

    def compose_agent_message(self, case: dict, service_date: str) -> str:
        """The opening message handed to the Insurance Agent.

        The agent reads nothing from the clinical side, so this message is its only source
        for the request: member, action, therapy, diagnosis code and display name, the
        referring provider, the date of service. It deliberately does not restate the
        workflow: the agent's system prompt owns PHASE A, and a message that re-specifies
        the steps would compete with it.

        NOTE: the billed amount has no source in either database yet, so the message says so
        and the agent records the claim at 0. See the follow-ups note in `data/`.
        """
        display = case.get("diagnosis_display")
        diagnosis = f"{case['related_diagnosis_code']} ({display})" if display else case["related_diagnosis_code"]
        provider = f"{case['provider_name']}, provider id {case['provider_id']}"
        if case.get("provider_specialty"):
            provider += f", {case['provider_specialty']}"
        return (
            f"Start the prior authorization process for member {case['member_id']}. "
            f"Action {case['action_id']}: therapy {case['proposed_treatment']}, "
            f"diagnosis {diagnosis}. "
            f"Referring physician {provider}. "
            f"Date of service {service_date}. "
            "No billed amount is available yet; record the claim with an amount of 0. "
            "Begin at PHASE A, Step 0."
        )

    @staticmethod
    def compose_clinical_review_message(member_id: str) -> str:
        """Hand the case to the Care-Coordination Agent (Steps 3-7).

        Carries only the member id: the agent calls `get_open_case(member_id)` to find the
        trace itself. The partial-coverage restriction is not in the message either: the
        Insurance Agent records it on the trace as `administrativeGates.coverageRestriction`.
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

    # --- the clinical sync ----------------------------------------------------

    def _sync(self, trace_id: str) -> None:
        """Bring the clinical record in line with the trace. Never raises: a sync failure
        must not stop the run, and the next call (every turn calls it) repairs it."""
        if not trace_id:
            return
        try:
            self.sync.sync_case(self.traces.get_by_key(trace_id))
        except Exception as e:  # noqa: BLE001
            logger.error("clinical sync failed for trace %s: %s", trace_id, e)

    # --- a turn that timed out -----------------------------------------------

    @staticmethod
    def _turn_complete(action: str, now: str) -> bool:
        """Has the work this turn exists to do landed on the trace?

        Not "has anything changed": the Insurance Agent's first turn passes through OPENED
        (still working) on its way to ADMIN_CLEARED, and its last turn through ROUTED on its way
        to CLOSED or ESCALATED, so those intermediate stages do not count. The care agent's one
        transition is the recommendation.
        """
        if action == NEEDS_START:
            return now in (NEEDS_CLINICAL_REVIEW, NEEDS_ROUTING, AWAITING_MEDICAL_DIRECTOR, DONE)
        if action == NEEDS_CLINICAL_REVIEW:
            return now in (NEEDS_ROUTING, AWAITING_MEDICAL_DIRECTOR, DONE)
        if action == NEEDS_ROUTING:
            return now in (AWAITING_MEDICAL_DIRECTOR, DONE)
        return False

    def _await_turn(self, member_id, action, action_id, agent, turn, trace_id, emit, result):
        """Keep reading the trace after a timed-out turn, for up to `grace_seconds`.

        The platform does not cancel an execution when it stops waiting on it, so the agent
        can still finish and write its result. Returns None if the turn's work landed (the run
        carries on exactly as if the call had returned), otherwise the reason it did not.

        The wait is not silent: the live-progress watcher keeps reporting steps as they land,
        and a `turn_waiting` event tells the viewer why nothing else is happening.
        """
        timeout_detail = result.get("error")
        logger.warning(
            "case for %s: the %s agent's turn timed out (%s); watching the trace for up to %.0fs",
            member_id, agent, timeout_detail, self.grace_seconds,
        )
        emit("turn_waiting", {
            "turn": turn, "agent": agent, "grace_seconds": self.grace_seconds,
            "detail": "The agent is taking longer than the platform waits for; "
                      "checking the case until its work appears.",
        })
        deadline = self._clock() + self.grace_seconds
        while True:
            tid = trace_id or self._resolve_trace_id(member_id, action_id)
            now = self.next_action(member_id, trace_id=tid)
            if self._turn_complete(action, now):
                logger.warning("case for %s: the %s agent's work landed after its call timed out", member_id, agent)
                return None
            remaining = deadline - self._clock()
            if remaining <= 0:
                return (
                    f"{timeout_detail} The case did not advance in the {self.grace_seconds:.0f}s "
                    f"allowed for the {agent} agent to finish (it was still {now!r})."
                )
            self._sleep(min(self.poll_seconds, remaining))

    # --- the run --------------------------------------------------------------

    def orchestrate(
        self, member_id: str, opening_message: str, publish=None, action_id: str = None
    ) -> list:
        """Drive the case to a stopping point, one agent turn at a time.

        `/invoke` blocks until an agent's turn is complete, so this is plain sequential
        code: invoke, re-read the record, decide, invoke again. Three turns in the normal
        case: insurance, care, insurance.

        Runs in a background task, never in a request. Returns the turns it took, for the
        log and for tests.

        Rules that keep it honest:
          * the decision to continue comes from what the agents wrote (`workflow.stage`),
            never from an assumption about what should have happened
          * a failed turn stops the chain, because invoking the next agent on top of a
            half-finished case makes the failure harder to see, not easier
          * after every turn the clinical record is synced from the trace, and if the run
            ends without a trace ever having been opened, the action `start()` flipped to
            `in_progress` is put back, so the member can press Start again

        `publish(event, data)` is optional and mirrors the turn structure to a live viewer.
        """
        emit = publish or (lambda event, data=None: None)
        turns = []
        # Learned after the first turn, then held: the case's identity for the rest of the
        # run, so closure cannot make it vanish.
        trace_id = None

        try:
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

                logger.warning("case for %s turn %d: %s -> %s agent", member_id, turn + 1, action, agent)
                emit("turn_started", {"turn": turn + 1, "action": action, "agent": agent})
                result = self.invoker.invoke(agent, message)

                # A timeout is not a failure: the agent may still be running, or may have
                # finished already. The trace is the record of what it did, so read it.
                recovered = False
                failure = None if result.get("ok") else result.get("error")
                if not result.get("ok") and result.get("ambiguous") and self.grace_seconds > 0:
                    failure = self._await_turn(
                        member_id, action, action_id, agent, turn + 1, trace_id, emit, result
                    )
                    recovered = failure is None
                turns.append({
                    "action": action, "invoked": agent,
                    "ok": bool(result.get("ok")) or recovered, "recovered": recovered,
                })

                if failure is not None:
                    logger.error("case for %s stopped: %s agent failed (%s)", member_id, agent, failure)
                    emit("error", {"agent": agent, "detail": failure})
                    break

                if trace_id is None:
                    trace_id = self._resolve_trace_id(member_id, action_id)
                self._sync(trace_id)
                finished = {"turn": turn + 1, "agent": agent, "trace_id": trace_id}
                if recovered:
                    finished["recovered"] = True
                emit("turn_finished", finished)

                # An agent that returned successfully without moving the case forward would
                # otherwise have this loop re-issue the same instruction until the cap.
                if self.next_action(member_id, trace_id=trace_id) == action:
                    logger.error(
                        "case for %s stopped: %s agent finished but the case still needs "
                        "%s — nothing was recorded on the trace",
                        member_id, agent, action,
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
                    member_id, _MAX_TURNS,
                )
                emit("error", {"detail": f"stopped after the {_MAX_TURNS}-turn cap"})
        finally:
            self._sync(trace_id)
            if action_id and not self._trace_for_action(member_id, action_id):
                # No trace was ever opened for this order: the run died (or was a dry run)
                # before the agent did anything. Put the order back to `pending`.
                self.profiles.rollback_start(member_id, action_id)

        return turns

    def start(self, member_id: str, service_date: str = None) -> dict:
        """Prepare an authorization run and return the handle immediately.

        Returns the payload plus a `run` callable the route schedules as a background task.
        Nothing is invoked here, but the physician's order is flipped to `in_progress`
        before returning (a compare-and-set, so a second click cannot also start a run);
        the endpoint stays synchronous and fast.

        `trace_id` and `claim_id` are absent by design: the agent mints them during Step 0,
        so the frontend discovers them by watching the case.
        """
        gate = self.check_can_start(member_id)
        if not gate.get("can_start"):
            return gate

        case = gate["case"]
        if not self.profiles.start_action(member_id, case["action_id"]):
            # Someone else flipped it between the check and now.
            return {
                "can_start": False,
                "reason": "already_in_progress",
                "member_id": member_id,
                "detail": f"Action {case['action_id']} was started by another request.",
            }

        as_of = service_date or date.today().isoformat()
        message = self.compose_agent_message(case, as_of)
        target = self.invoker.describe(INSURANCE_AGENT)

        def run(publish=None):
            self.orchestrate(member_id, message, publish=publish, action_id=case["action_id"])

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
            # Null until the agent's Step 0 writes them. The frontend watches the member
            # for a trace to appear rather than expecting them here.
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
