"""Send a message to an agent.

Local `agentic dev` exposes the Orchestration Engine through the playground
container, so a plain HTTP POST is enough:

    curl -X POST http://localhost:3001/invoke \
         -H 'Content-Type: application/json' \
         -d '{"message": "Hello"}'

The deployed Platform API is a different transport (bearer token, workspace
targeting) and is not wired up yet — the agent has no registered workspace. Mode
selection lives here so that when it is, only this file changes.

`/invoke` blocks until the agent finishes its whole run, which for a prior
authorization is minutes. It is also plain synchronous `urllib`, so it blocks the
thread it is called on and must never be called on the event loop.

That blocking is what makes the sequential chain work — a turn returning *is* the
signal the agent is done — so the caller does not try to avoid it, it moves it off
the loop: `start_authorization` hands the whole orchestration to
`loop.run_in_executor`, detached, and streams progress read off the audit trace
meanwhile. Anything reusing this invoker owes it the same treatment.
"""

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# Where each agent's local playground publishes /invoke. Overridable because
# `agentic dev` assigns host ports and the two agents cannot share one.
_DEFAULT_INSURANCE_AGENT_URL = "http://localhost:3001"
_DEFAULT_CARE_AGENT_URL = "http://localhost:3002"

# dry_run records the message it would have sent and returns. It is the default so
# the workflow endpoints are testable without a running agent stack, and so a demo
# backend cannot silently fire agent runs at whatever happens to be on port 3001.
MODE_DRY_RUN = "dry_run"
MODE_HTTP = "http"

INSURANCE_AGENT = "insurance"
CARE_AGENT = "care_coordination"


class AgentInvoker:
    """Fire-and-forget messages to the agents.

    Read from the environment rather than passed in, because the caller is an HTTP
    route with no business knowing the transport:

        AGENT_INVOKE_MODE       dry_run (default) | http
        INSURANCE_AGENT_URL     default http://localhost:3001
        CARE_AGENT_URL          default http://localhost:3002
        AGENT_INVOKE_TIMEOUT    seconds to wait for the run (default 900)

    From inside a container, `localhost` is the container — use
    http://host.docker.internal:3001 instead.
    """

    def __init__(self, mode: str = None, timeout: float = None):
        self.mode = (mode or os.getenv("AGENT_INVOKE_MODE") or MODE_DRY_RUN).strip().lower()
        self.timeout = float(timeout or os.getenv("AGENT_INVOKE_TIMEOUT") or 900)
        self.urls = {
            INSURANCE_AGENT: (
                os.getenv("INSURANCE_AGENT_URL") or _DEFAULT_INSURANCE_AGENT_URL
            ).rstrip("/"),
            CARE_AGENT: (
                os.getenv("CARE_AGENT_URL") or _DEFAULT_CARE_AGENT_URL
            ).rstrip("/"),
        }

    def target_url(self, agent: str) -> str:
        try:
            return f"{self.urls[agent]}/invoke"
        except KeyError:
            raise ValueError(
                f"Unknown agent {agent!r}. Expected one of: {', '.join(self.urls)}."
            )

    def describe(self, agent: str) -> dict:
        """What this invoker would do, for the endpoint to report back."""
        return {"mode": self.mode, "agent": agent, "url": self.target_url(agent)}

    def invoke(self, agent: str, message: str, session_id: str = None) -> dict:
        """Send `message` to `agent` and wait for the run to finish.

        Blocking and slow by nature — run it in the background, never in a request.
        Never raises: a failed agent run must not surface as a 500 on an endpoint
        that already returned 202. Failures are logged and returned as `ok: False`.
        """
        url = self.target_url(agent)

        if self.mode == MODE_DRY_RUN:
            # WARNING, not INFO: no agent ran. The endpoint still answers 202, so this
            # line is the only signal that the case was not actually started — and
            # uvicorn's default log config drops INFO from application loggers, which
            # would make a dry run silently indistinguishable from a real one.
            logger.warning(
                "[dry_run] no agent invoked. Would POST %s\n%s",
                url,
                json.dumps({"message": message}, indent=2),
            )
            return {"ok": True, "mode": MODE_DRY_RUN, "url": url, "message": message}

        body = {"message": message}
        if session_id:
            body["session_id"] = session_id

        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
            logger.info("agent %s run finished (%s)", agent, url)
            try:
                return {"ok": True, "mode": self.mode, "url": url, "response": json.loads(raw)}
            except json.JSONDecodeError:
                # OE may answer with a stream or plain text; the body is a courtesy
                # here, not the result. Progress is read off the audit trace.
                return {"ok": True, "mode": self.mode, "url": url, "response": raw[:2000]}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:2000]
            logger.error("agent %s rejected the message: %s %s", agent, e.code, detail)
            return {"ok": False, "mode": self.mode, "url": url, "error": f"{e.code}: {detail}"}
        except Exception as e:
            # Includes a stack that is not listening, and the timeout on a run that
            # outlives AGENT_INVOKE_TIMEOUT.
            logger.error("agent %s invoke failed: %s", agent, e)
            return {"ok": False, "mode": self.mode, "url": url, "error": str(e)}
