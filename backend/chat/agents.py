"""The two agents the chat can talk to.

Deliberately the *same* agents the authorization workflow drives, reached the same
way — so the chat and the workflow can never drift onto different deployments or
transports. Mode selection mirrors `authorization/agent_invoker.py` exactly (same env
var names, on purpose, same fail-loud contract on missing credentials): a local
`agentic dev` playground when `LOCAL_AGENTIC_DEPLOYMENT` is true (the default), or a
deployed remote target — project/workspace-scoped URL, bearer auth — when it is false.
See `chat-resources/CLOUD-AGENT-MIGRATION.md` for why the design looks like this.

Unlike the authorization workflow, chat needs the streaming endpoint (`/invokeStream`),
so `target()` hands back a base URL only — the caller appends `/invoke` or
`/invokeStream` — plus whatever headers every request to that agent needs.
"""

import os

INSURANCE_AGENT = "insurance"
CARE_AGENT = "care_coordination"

_DEFAULT_INSURANCE_AGENT_URL = "http://localhost:3001"
_DEFAULT_CARE_AGENT_URL = "http://localhost:3002"

_LOCAL_ENV_VAR = {
    INSURANCE_AGENT: "INSURANCE_AGENT_URL",
    CARE_AGENT: "CARE_AGENT_URL",
}
_LOCAL_DEFAULT_URL = {
    INSURANCE_AGENT: _DEFAULT_INSURANCE_AGENT_URL,
    CARE_AGENT: _DEFAULT_CARE_AGENT_URL,
}

# Env var prefix each agent's platform credentials are read under — the same mapping
# `agent_invoker._PLATFORM_ENV_PREFIX` uses, for the same reason: `care_coordination` is
# a workflow role, not an env var namespace, so it is spelled out rather than guessed.
_PLATFORM_ENV_PREFIX = {
    INSURANCE_AGENT: "INSURANCE_AGENT",
    CARE_AGENT: "CARE_AGENT",
}

# `label` and `blurb` are display-only and travel to the browser; nothing here is secret,
# which is why this whole registry can be served by GET /api/chat/agents.
AGENTS = {
    INSURANCE_AGENT: {
        "id": INSURANCE_AGENT,
        "label": "Insurance Agent",
        "blurb": "Eligibility, coverage, claims and benefits",
        "accent": "#00684a",
    },
    CARE_AGENT: {
        "id": CARE_AGENT,
        "label": "Care Coordination Agent",
        "blurb": "Clinical history, guidelines and treatment",
        "accent": "#8b5cf6",
    },
}

DEFAULT_AGENT = INSURANCE_AGENT


def is_known(agent_id: str) -> bool:
    return agent_id in AGENTS


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("false", "0", "no", "")


def _local_mode() -> bool:
    return _env_flag("LOCAL_AGENTIC_DEPLOYMENT", default=True)


def _platform_credentials(agent_id: str) -> dict:
    """Read and validate one agent's platform credentials.

    Fails loudly, naming exactly which env var is missing — the same contract
    `agent_invoker._platform_credentials` follows, so a misconfigured deploy fails the
    same way for chat as it does for the authorization workflow, instead of chat quietly
    trying to reach `localhost` from inside a pod with nothing listening there.
    """
    prefix = _PLATFORM_ENV_PREFIX[agent_id]
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
            f"LOCAL_AGENTIC_DEPLOYMENT=false (platform mode) for agent {agent_id!r} "
            f"but missing env var(s): {', '.join(missing)}"
        )
    creds["base_url"] = creds["base_url"].rstrip("/")
    return creds


def target(agent_id: str) -> dict:
    """Where and how to reach this agent: a base URL (caller appends `/invoke` or
    `/invokeStream`) plus any headers every request to it needs.

    Raises `KeyError` for an unknown agent. Callers must validate first: answering as
    the wrong agent is worse than erroring, because the reply would be attributed to an
    agent that never said it.
    """
    if agent_id not in AGENTS:
        raise KeyError(agent_id)

    if _local_mode():
        url = os.getenv(_LOCAL_ENV_VAR[agent_id]) or _LOCAL_DEFAULT_URL[agent_id]
        return {"base_url": url.rstrip("/"), "headers": {}}

    creds = _platform_credentials(agent_id)
    base_url = (
        f"{creds['base_url']}/projects/{creds['project_id']}"
        f"/workspaces/{creds['workspace_id']}"
    )
    return {"base_url": base_url, "headers": {"Authorization": f"Bearer {creds['api_key']}"}}


def public_list() -> list[dict]:
    """The registry as the agent picker needs it. No URLs — the browser never calls an
    agent directly, it always goes through this backend."""
    return [
        {
            "id": a["id"],
            "label": a["label"],
            "blurb": a["blurb"],
            "accent": a["accent"],
        }
        for a in AGENTS.values()
    ]
