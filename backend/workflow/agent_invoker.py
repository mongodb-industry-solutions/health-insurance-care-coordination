"""Send a message to a deployed agent, and wait for its turn to finish.

The agents run on Atlas Agent Engine. The call itself (OAuth token, versioned `Accept` header,
URL shape, `X-Session-ID`) lives in `shared/aae_client.py`, shared with the chat; this module
adds what the workflow needs on top of it: a mode switch and a result shaped for the orchestrator.

`/invoke` blocks until the agent finishes its whole turn, which for a prior authorization is
minutes. It is plain synchronous HTTP, so it blocks the thread it is called on and must never
be called on the event loop. That blocking is what makes the sequential chain work: a turn
returning *is* the signal the agent is done. So the caller does not try to avoid it, it moves
it off the loop: `start_authorization` hands the whole orchestration to `loop.run_in_executor`,
detached, and streams progress read off the audit trace meanwhile. Anything reusing this
invoker owes it the same treatment.

Each turn is a fresh session (no `X-Session-ID`): both agents release their sandboxes when a
turn ends, and a prior authorization is three independent turns with the other agent's turn in
between, so there is nothing to continue.
"""

import json
import logging
import os

from shared.aae_client import (
    AgentEngineError,
    CARE_AGENT,
    INSURANCE_AGENT,
    get_client,
)

logger = logging.getLogger(__name__)

# dry_run records the message it would have sent and returns. It is the default so the
# workflow endpoints are testable without credentials, and so a demo backend cannot silently
# fire agent runs at a real deployment.
MODE_DRY_RUN = "dry_run"
# Calls the deployed agents on Atlas Agent Engine.
MODE_PLATFORM = "platform"

__all__ = ["AgentInvoker", "INSURANCE_AGENT", "CARE_AGENT", "MODE_DRY_RUN", "MODE_PLATFORM"]


class AgentInvoker:
    """Fire-and-wait messages to the agents.

    Read from the environment rather than passed in, because the caller is an HTTP route with
    no business knowing the transport:

        AGENT_INVOKE_MODE      dry_run (default) | anything else = call the deployed agents
        AGENT_INVOKE_TIMEOUT   seconds to wait for one turn (default 900)

    In platform mode the credentials and targets come from the environment (see
    `shared/aae_client.py`): AAE_CLIENT_ID, AAE_CLIENT_SECRET, AAE_PROJECT_ID (or a per-agent
    `*_PROJECT_ID`) and `INSURANCE_AGENT_WORKSPACE_ID` / `CARE_AGENT_WORKSPACE_ID`. A missing one
    fails at construction, naming every variable that is missing, never as a run that looks
    like it started and then silently stalls.

    There is no local mode: the agents are only ever reached where they are deployed.
    """

    def __init__(self, mode: str = None, timeout: float = None, client=None):
        raw_mode = (mode or os.getenv("AGENT_INVOKE_MODE") or MODE_DRY_RUN).strip().lower()
        self.mode = MODE_DRY_RUN if raw_mode == MODE_DRY_RUN else MODE_PLATFORM
        self.timeout = float(timeout or os.getenv("AGENT_INVOKE_TIMEOUT") or 900)
        self._client = client
        if self.mode == MODE_PLATFORM:
            self.client.validate()

    @property
    def client(self):
        return self._client or get_client()

    def target_url(self, agent: str) -> str:
        if self.mode == MODE_PLATFORM:
            return self.client.url(agent, "invoke")
        if agent not in (INSURANCE_AGENT, CARE_AGENT):
            raise ValueError(f"Unknown agent {agent!r}. Expected one of: {INSURANCE_AGENT}, {CARE_AGENT}.")
        return f"dry_run://{agent}"

    def describe(self, agent: str) -> dict:
        """What this invoker would do, for the endpoint to report back."""
        return {"mode": self.mode, "agent": agent, "url": self.target_url(agent)}

    def invoke(self, agent: str, message: str, session_id: str = None) -> dict:
        """Send `message` to `agent` and wait for the turn to finish.

        Blocking and slow by nature: run it in the background, never in a request. Never
        raises: a failed agent run must not surface as a 500 on an endpoint that already
        returned 202. Failures are logged and returned as `ok: False` with an `error`.
        """
        url = self.target_url(agent)

        if self.mode == MODE_DRY_RUN:
            # WARNING, not INFO: no agent ran. The endpoint still answers 202, so this line is
            # the only signal that the case was not actually started — and uvicorn's default
            # log config drops INFO from application loggers, which would make a dry run
            # silently indistinguishable from a real one.
            logger.warning(
                "[dry_run] no agent invoked. Would call %s\n%s",
                url,
                json.dumps({"message": message}, indent=2),
            )
            return {"ok": True, "mode": MODE_DRY_RUN, "url": url, "message": message}

        try:
            result = self.client.invoke(agent, message, session_id=session_id, timeout=self.timeout)
        except AgentEngineError as e:
            logger.error("agent %s invoke failed: %s", agent, e)
            # `ambiguous`: the call was sent and timed out, so the agent may still be running
            # (or have finished). The orchestrator watches the trace instead of giving up.
            return {"ok": False, "mode": self.mode, "url": url, "error": str(e),
                    "ambiguous": e.ambiguous}
        except Exception as e:  # noqa: BLE001 — never raise out of a detached run
            logger.exception("agent %s invoke failed unexpectedly", agent)
            return {"ok": False, "mode": self.mode, "url": url, "error": f"{type(e).__name__}: {e}"}

        out = {
            "ok": result["ok"],
            "mode": self.mode,
            "url": url,
            "status": result.get("status"),
            "response": result.get("response"),
            # Captured for correlating a backend run with a platform-side execution when
            # debugging; nothing here reads it back.
            "execution_id": result.get("execution_id"),
            "session_id": result.get("session_id"),
        }
        if not result["ok"]:
            out["error"] = result.get("error")
            logger.error("agent %s run did not complete: %s", agent, out["error"])
        return out
