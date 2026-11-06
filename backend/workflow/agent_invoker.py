"""Send a message to an agent.

Local `agentic dev` exposes the Orchestration Engine through the playground
container, so a plain HTTP POST is enough:

    curl -X POST http://localhost:3001/invoke \
         -H 'Content-Type: application/json' \
         -d '{"message": "Hello"}'

Deployed agents run on a different, remote deployment target instead, which speaks
a different wire contract — see `chat-resources/CLOUD-AGENT-MIGRATION.md` for the
specifics. `LOCAL_AGENTIC_DEPLOYMENT` (default true) picks between the two — see the
class docstring — so an existing local/dry-run setup is byte-for-byte unaffected.
Mode selection lives here so that going from one to the other never touches the
caller.

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
# The deployed remote transport: project/workspace-scoped URL, bearer auth.
MODE_PLATFORM = "platform"

INSURANCE_AGENT = "insurance"
CARE_AGENT = "care_coordination"

# Env var prefix each agent's platform credentials are read under. Not derived from
# the agent key — `care_coordination` is a workflow role, not an env var namespace —
# so the mapping is spelled out instead of guessed from the string.
_PLATFORM_ENV_PREFIX = {
    INSURANCE_AGENT: "INSURANCE_AGENT",
    CARE_AGENT: "CARE_AGENT",
}


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("false", "0", "no", "")


class AgentInvoker:
    """Fire-and-forget messages to the agents.

    Read from the environment rather than passed in, because the caller is an HTTP
    route with no business knowing the transport:

        AGENT_INVOKE_MODE         dry_run (default) | anything else
        LOCAL_AGENTIC_DEPLOYMENT  true (default) | false

    `AGENT_INVOKE_MODE=dry_run` always wins and is unaffected by everything below —
    it is still the testing default. Otherwise `LOCAL_AGENTIC_DEPLOYMENT` decides:

        # local playground (LOCAL_AGENTIC_DEPLOYMENT=true, the default)
        INSURANCE_AGENT_URL       default http://localhost:3001
        CARE_AGENT_URL            default http://localhost:3002

        # deployed remote target (LOCAL_AGENTIC_DEPLOYMENT=false)
        AGENT_BASE_URL            base URL of the remote deployment target
        INSURANCE_AGENT_API_KEY / INSURANCE_AGENT_PROJECT_ID / INSURANCE_AGENT_WORKSPACE_ID
        CARE_AGENT_API_KEY / CARE_AGENT_PROJECT_ID / CARE_AGENT_WORKSPACE_ID

        AGENT_INVOKE_TIMEOUT      seconds to wait for the run (default 900)

    From inside a local container talking to a local playground, `localhost` is the
    container — use http://host.docker.internal:3001 instead. A deployed backend
    reaches the remote target over the public `AGENT_BASE_URL`, so this does not
    apply there.

    See `chat-resources/CLOUD-AGENT-MIGRATION.md` for why the design looks like this.
    """

    def __init__(self, mode: str = None, timeout: float = None):
        raw_mode = (mode or os.getenv("AGENT_INVOKE_MODE") or MODE_DRY_RUN).strip().lower()
        if raw_mode == MODE_DRY_RUN:
            self.mode = MODE_DRY_RUN
        else:
            local = _env_flag("LOCAL_AGENTIC_DEPLOYMENT", default=True)
            self.mode = MODE_HTTP if local else MODE_PLATFORM
        self.timeout = float(timeout or os.getenv("AGENT_INVOKE_TIMEOUT") or 900)

        self.urls = {
            INSURANCE_AGENT: (
                os.getenv("INSURANCE_AGENT_URL") or _DEFAULT_INSURANCE_AGENT_URL
            ).rstrip("/"),
            CARE_AGENT: (
                os.getenv("CARE_AGENT_URL") or _DEFAULT_CARE_AGENT_URL
            ).rstrip("/"),
        }

        # Fail at construction, not on first invoke: a missing secret must show up as
        # a startup/first-request error naming exactly which env var is missing, never
        # as a run that looks like it started and then silently stalls.
        self._platform = (
            {agent: self._platform_credentials(agent) for agent in _PLATFORM_ENV_PREFIX}
            if self.mode == MODE_PLATFORM
            else {}
        )

    @staticmethod
    def _platform_credentials(agent: str) -> dict:
        prefix = _PLATFORM_ENV_PREFIX[agent]
        env_names = {
            "base_url": "AGENT_BASE_URL",
            "api_key": f"{prefix}_API_KEY",
            "project_id": f"{prefix}_PROJECT_ID",
            "workspace_id": f"{prefix}_WORKSPACE_ID",
        }
        creds = {key: os.getenv(env_name) for key, env_name in env_names.items()}
        missing = [env_name for key, env_name in env_names.items() if not creds[key]]
        if missing:
            raise RuntimeError(
                f"LOCAL_AGENTIC_DEPLOYMENT=false (platform mode) for agent {agent!r} "
                f"but missing env var(s): {', '.join(missing)}"
            )
        creds["base_url"] = creds["base_url"].rstrip("/")
        return creds

    def target_url(self, agent: str) -> str:
        if self.mode == MODE_PLATFORM:
            try:
                creds = self._platform[agent]
            except KeyError:
                raise ValueError(
                    f"Unknown agent {agent!r}. Expected one of: "
                    f"{', '.join(_PLATFORM_ENV_PREFIX)}."
                )
            return (
                f"{creds['base_url']}/projects/{creds['project_id']}"
                f"/workspaces/{creds['workspace_id']}/invoke"
            )
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

        headers = {"Content-Type": "application/json"}
        if self.mode == MODE_PLATFORM:
            headers["Authorization"] = f"Bearer {self._platform[agent]['api_key']}"

        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
            logger.info("agent %s run finished (%s)", agent, url)
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                # OE may answer with a stream or plain text; the body is a courtesy
                # here, not the result. Progress is read off the audit trace.
                return {"ok": True, "mode": self.mode, "url": url, "response": raw[:2000]}
            result = {"ok": True, "mode": self.mode, "url": url, "response": parsed}
            # Captured purely for logging / correlating a backend run with a
            # platform-side execution when debugging — nothing here reads it back.
            execution_id = parsed.get("execution_id") if isinstance(parsed, dict) else None
            if execution_id:
                result["execution_id"] = execution_id
            return result
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:2000]
            logger.error("agent %s rejected the message: %s %s", agent, e.code, detail)
            return {"ok": False, "mode": self.mode, "url": url, "error": f"{e.code}: {detail}"}
        except Exception as e:
            # Includes a stack that is not listening, and the timeout on a run that
            # outlives AGENT_INVOKE_TIMEOUT.
            logger.error("agent %s invoke failed: %s", agent, e)
            return {"ok": False, "mode": self.mode, "url": url, "error": str(e)}
