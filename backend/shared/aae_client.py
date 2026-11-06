"""Client for invoking deployed Atlas Agent Engine (AAE) agents from the backend.

One implementation, shared by the authorization workflow (`workflow/agent_invoker.py`, blocking
`invoke`) and the chat (`chat/service.py`, streaming `invokeStream`), so the URL shape, the
credentials and the token live in one place. Standard library only.

The contract (Atlas Agent Engine, Public Preview; see `backend/docs/Invoke AAE Agent from
Backend.md`):

* `POST {base}/api/v1/oauth/token` with HTTP Basic auth (`client_id:client_secret`) and
  `grant_type=client_credentials` returns `{access_token, expires_in}`. The token lasts one hour
  and the endpoint answers 429 if asked too often, so ONE token is cached per process and
  shared by both agents (they use the same service account), behind a lock: the orchestrator and
  the chat both run on threads.
* `POST {base}/api/v1/projects/{project}/workspaces/{workspace}/invoke` with
  `Authorization: Bearer <token>` and an `Accept` header that pins the API contract.
  The body is `{"message": ...}`. The reply is `{success, response, execution_id, status}`.
  The session id travels in the `X-Session-ID` header, in both directions, never in the body.
* `.../invokeStream` is the same call as Server-Sent Events: `data:` frames carrying a JSON object
  with a `chunk_type` (`text`, `step`, `done`, `error`, ...). It needs `text/event-stream` in
  `Accept`.

Behaviours that matter here:

* A 200 is not a success. `ok` is true only when `success` is not false AND `status` is
  `completed`; anything else (an error, a cancellation, a suspension for review) is reported as
  a failed turn with the platform's own detail.
* A blocking turn can run for minutes, so the read timeout is the caller's (default 15 minutes);
  only the token request has a short one.
* Retries are deliberately narrow, because the docs warn against retrying after an ambiguous
  failure: a 401 is retried once with a fresh token (the request was refused, not run), and a
  "pool full" refusal is retried with back-off (the platform says a new invoke *fails*). A
  timeout or a dropped connection is never retried: the agent may still be running.
* Secrets are never logged or put in an error message.

Configuration, read from the environment on every call (so a test can swap it):

    AAE_CLIENT_ID, AAE_CLIENT_SECRET     the service account
    AAE_PROJECT_ID                       the project (each agent may override it below)
    INSURANCE_AGENT_WORKSPACE_ID, CARE_AGENT_WORKSPACE_ID
    INSURANCE_AGENT_PROJECT_ID, CARE_AGENT_PROJECT_ID     optional per-agent project override
    AAE_BASE_URL         default https://agentengine.mongodb.com
    AAE_API_ACCEPT       default application/vnd.agent-engine-2026-09-20-preview+json
    AAE_POOL_RETRIES     default 3 (back-off 5s, 15s, 30s)
"""

import base64
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://agentengine.mongodb.com"
# Pinned on every versioned request so a newly published default cannot silently change the
# request/response shape this integration depends on.
DEFAULT_ACCEPT = "application/vnd.agent-engine-2026-09-20-preview+json"

INSURANCE_AGENT = "insurance"
CARE_AGENT = "care_coordination"

# The agent key is a workflow role, not an env var namespace, so the prefix is spelled out.
ENV_PREFIX = {INSURANCE_AGENT: "INSURANCE_AGENT", CARE_AGENT: "CARE_AGENT"}

# The token call is quick; the agent call is not.
_TOKEN_TIMEOUT = 15.0
_TOKEN_REFRESH_MARGIN = 60  # seconds: refresh before the token is nearly expired
_POOL_RETRY_DELAYS = (5.0, 15.0, 30.0)


class AgentEngineError(RuntimeError):
    """A call to Agent Engine failed. The message is safe to log and to show: it never
    contains a credential."""

    def __init__(self, message: str, status: int = None, detail: str = None, ambiguous: bool = False):
        super().__init__(message)
        self.status = status
        self.detail = detail
        # True when the request was sent but its outcome is unknown: a timeout, on either side.
        # The agent may still be running, or may have finished, so the caller must find out
        # from the record it writes, not assume it failed.
        self.ambiguous = ambiguous


class AgentEngineConfigurationError(AgentEngineError):
    """A required environment variable is not set."""


def _snippet(text: str, limit: int = 600) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _is_timeout(error: BaseException) -> bool:
    """A timeout while waiting on a request that was already sent."""
    if isinstance(error, TimeoutError):
        return True
    return isinstance(error, urllib.error.URLError) and isinstance(error.reason, TimeoutError)


def _is_platform_timeout(status, detail: str) -> bool:
    """The platform gave up waiting on the agent (`AGENT_TIMEOUT`, or a gateway 504). The
    execution is not cancelled by that: the docs say it keeps running on the server."""
    return status == 504 or "agent_timeout" in (detail or "").lower()


def _is_pool_full(detail: str) -> bool:
    lowered = (detail or "").lower()
    return "pool full" in lowered or "pool_full" in lowered


class AtlasAgentEngine:
    def __init__(self, env=None, clock=time.monotonic, sleep=time.sleep, opener=None):
        # `env` defaults to the live process environment, read on every call.
        self._env = env if env is not None else os.environ
        self._clock = clock
        self._sleep = sleep
        self._opener = opener or urllib.request.urlopen
        self._lock = threading.Lock()
        self._token = None
        self._refresh_at = 0.0

    # ------------------------------------------------------------------ configuration

    def _get(self, name: str) -> str:
        return (self._env.get(name) or "").strip()

    @property
    def base_url(self) -> str:
        return (self._get("AAE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")

    @property
    def accept(self) -> str:
        return self._get("AAE_API_ACCEPT") or DEFAULT_ACCEPT

    def _pool_delays(self) -> tuple:
        raw = self._get("AAE_POOL_RETRIES")
        retries = int(raw) if raw.isdigit() else len(_POOL_RETRY_DELAYS)
        delays = list(_POOL_RETRY_DELAYS)
        while len(delays) < retries:
            delays.append(delays[-1])
        return tuple(delays[:retries])

    def _target(self, agent: str) -> tuple:
        """(project_id, workspace_id) for one agent, plus the names of anything missing."""
        if agent not in ENV_PREFIX:
            raise ValueError(f"Unknown agent {agent!r}. Expected one of: {', '.join(ENV_PREFIX)}.")
        prefix = ENV_PREFIX[agent]
        project = self._get(f"{prefix}_PROJECT_ID") or self._get("AAE_PROJECT_ID")
        workspace = self._get(f"{prefix}_WORKSPACE_ID")
        missing = []
        if not project:
            missing.append(f"{prefix}_PROJECT_ID (or AAE_PROJECT_ID)")
        if not workspace:
            missing.append(f"{prefix}_WORKSPACE_ID")
        return project, workspace, missing

    def validate(self, agents=(INSURANCE_AGENT, CARE_AGENT)) -> None:
        """Raise `AgentEngineConfigurationError` naming EVERY missing variable, so a
        misconfigured deployment is fixed in one pass rather than one variable at a time."""
        missing = [n for n in ("AAE_CLIENT_ID", "AAE_CLIENT_SECRET") if not self._get(n)]
        for agent in agents:
            missing += self._target(agent)[2]
        if missing:
            raise AgentEngineConfigurationError(
                "Atlas Agent Engine is not configured; missing: " + ", ".join(missing) + "."
            )

    def url(self, agent: str, endpoint: str = "invoke") -> str:
        project, workspace, missing = self._target(agent)
        if missing:
            raise AgentEngineConfigurationError(
                "Atlas Agent Engine is not configured; missing: " + ", ".join(missing) + "."
            )
        return f"{self.base_url}/api/v1/projects/{project}/workspaces/{workspace}/{endpoint}"

    # ------------------------------------------------------------------------- token

    def get_token(self, stale: str = None) -> str:
        """The shared access token, fetched at most once per lifetime.

        `stale` is a token the caller was just refused with. If another thread has already
        replaced it, that newer token is returned instead of asking again: with two threads
        both refused at once, the token endpoint (rate-limited) is called once, not twice.
        """
        with self._lock:
            now = self._clock()
            if stale is not None and self._token is not None and self._token != stale:
                return self._token
            if stale is None and self._token is not None and now < self._refresh_at:
                return self._token

            client_id, client_secret = self._get("AAE_CLIENT_ID"), self._get("AAE_CLIENT_SECRET")
            if not client_id or not client_secret:
                missing = [n for n, v in (("AAE_CLIENT_ID", client_id), ("AAE_CLIENT_SECRET", client_secret)) if not v]
                raise AgentEngineConfigurationError(
                    "Atlas Agent Engine is not configured; missing: " + ", ".join(missing) + "."
                )
            basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            request = urllib.request.Request(
                f"{self.base_url}/api/v1/oauth/token",
                data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                method="POST",
            )
            try:
                with self._opener(request, timeout=_TOKEN_TIMEOUT) as response:
                    data = json.loads(response.read().decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as e:
                detail = _snippet(e.read().decode("utf-8", errors="replace"))
                hint = " (the token endpoint is rate-limited: too many token requests)" if e.code == 429 else ""
                raise AgentEngineError(
                    f"Could not get an access token ({e.code}){hint}: {detail}", status=e.code, detail=detail
                ) from e
            except (urllib.error.URLError, OSError, ValueError) as e:
                raise AgentEngineError(f"Could not reach the Agent Engine token endpoint: {e}") from e

            token = data.get("access_token") if isinstance(data, dict) else None
            if not token:
                raise AgentEngineError("The Agent Engine token endpoint returned no access_token.")
            lifetime = int(data.get("expires_in") or 3600)
            self._token = token
            self._refresh_at = now + max(0, lifetime - _TOKEN_REFRESH_MARGIN)
            return token

    # ------------------------------------------------------------------------- calls

    def _send(self, agent: str, endpoint: str, message: str, session_id, timeout: float, stream: bool):
        """POST `message`; return the open response (the caller closes it).

        Retries only what is safe to retry: a 401 once, with a fresh token, and a "pool full"
        refusal, with back-off. Everything else is raised as it is.
        """
        self.validate((agent,))  # names every missing variable, credentials included
        url = self.url(agent, endpoint)
        body = json.dumps({"message": message}).encode("utf-8")
        accept = f"text/event-stream, {self.accept}" if stream else self.accept
        token = self.get_token()
        refreshed = False
        delays = list(self._pool_delays())

        while True:
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": accept,
                "Content-Type": "application/json",
            }
            if session_id:
                headers["X-Session-ID"] = session_id
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                return self._opener(request, timeout=timeout)
            except urllib.error.HTTPError as e:
                detail = _snippet(e.read().decode("utf-8", errors="replace"))
                if e.code == 401 and not refreshed:
                    refreshed = True
                    token = self.get_token(stale=token)
                    continue
                if _is_pool_full(detail) and delays:
                    delay = delays.pop(0)
                    logger.warning("agent %s: no free sandbox (pool full); retrying in %.0fs", agent, delay)
                    self._sleep(delay)
                    continue
                raise AgentEngineError(
                    f"Agent Engine rejected the call to the {agent} agent ({e.code}): {detail}",
                    status=e.code, detail=detail,
                    ambiguous=_is_platform_timeout(e.code, detail),
                ) from e
            except (urllib.error.URLError, OSError) as e:
                # Includes a timeout and a dropped connection. NOT retried: the agent may
                # still be running, and repeating it could repeat its actions.
                raise AgentEngineError(
                    f"Could not reach the {agent} agent: {e}", ambiguous=_is_timeout(e)
                ) from e

    @staticmethod
    def _interpret(raw: str, session_id) -> dict:
        """Turn a blocking invoke reply into `{ok, status, response, execution_id, ...}`."""
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return {"ok": False, "status": None, "response": None, "execution_id": None,
                    "session_id": session_id,
                    "error": f"Agent Engine returned a reply that is not a JSON object: {_snippet(raw, 300)}"}

        status = str(body.get("status") or "").strip().lower()
        ok = body.get("success") is not False and status == "completed"
        result = {
            "ok": ok,
            "status": body.get("status"),
            "response": body.get("response"),
            "execution_id": body.get("execution_id"),
            "session_id": session_id,
        }
        if not ok:
            reason = body.get("suspend_reason")
            detail = body.get("error") or body.get("message") or body.get("detail") or reason
            if isinstance(detail, (dict, list)):
                detail = json.dumps(detail)
            result["error"] = (
                f"The agent run did not complete (status {body.get('status')!r})"
                + (f": {detail}" if detail else ".")
            )
            if reason:
                result["suspend_reason"] = reason
        return result

    def invoke(self, agent: str, message: str, session_id: str = None, timeout: float = 900.0) -> dict:
        """One blocking turn. Raises `AgentEngineError` if the call itself fails; an agent run
        that fails comes back as `{"ok": False, "error": ...}`."""
        started = self._clock()
        response = self._send(agent, "invoke", message, session_id, timeout, stream=False)
        try:
            with response:
                raw = response.read().decode("utf-8", errors="replace")
                returned_session = response.headers.get("X-Session-ID")
        except (OSError, ValueError) as e:
            raise AgentEngineError(
                f"The {agent} agent did not answer within {timeout:g}s ({e}). It may still be running.",
                ambiguous=True,
            ) from e
        result = self._interpret(raw, returned_session)
        logger.info(
            "agent %s turn %s (status=%s, execution_id=%s, %.1fs)",
            agent, "ok" if result["ok"] else "FAILED", result["status"], result["execution_id"],
            self._clock() - started,
        )
        return result

    def open_stream(self, agent: str, message: str, session_id: str = None, timeout: float = 180.0):
        """Open `invokeStream` and return the live response (SSE); the caller reads and closes
        it. `response.headers.get("X-Session-ID")` is the session to continue."""
        return self._send(agent, "invokeStream", message, session_id, timeout, stream=True)


# --------------------------------------------------------------------- process-wide client

_client = None
_client_lock = threading.Lock()


def get_client() -> AtlasAgentEngine:
    """The one client per process: its token cache is shared by the workflow and the chat."""
    global _client
    with _client_lock:
        if _client is None:
            _client = AtlasAgentEngine()
        return _client


def reset_client() -> None:
    """Drop the cached client and its token (tests, or after the credentials change)."""
    global _client
    with _client_lock:
        _client = None
