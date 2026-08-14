"""The two agents the chat can talk to.

Deliberately the *same* agents the authorization workflow drives, reached at the same
URLs — so the chat and the workflow can never drift onto different deployments. The
env var names are shared with `authorization/agent_invoker.py` on purpose.

Only the local (`agentic dev`) transport is implemented here. The cloud transport is
designed in CLOUD-AGENT-MIGRATION.md and is intentionally not wired up yet; when it is,
`base_url()` is the single place that changes.
"""

import os

INSURANCE_AGENT = "insurance"
CARE_AGENT = "care_coordination"

_DEFAULT_INSURANCE_AGENT_URL = "http://localhost:3001"
_DEFAULT_CARE_AGENT_URL = "http://localhost:3002"

# `label` and `blurb` are display-only and travel to the browser; nothing here is secret,
# which is why this whole registry can be served by GET /api/chat/agents.
AGENTS = {
    INSURANCE_AGENT: {
        "id": INSURANCE_AGENT,
        "label": "Insurance Agent",
        "blurb": "Eligibility, coverage, claims and benefits",
        "accent": "#00684a",
        "env_var": "INSURANCE_AGENT_URL",
        "default_url": _DEFAULT_INSURANCE_AGENT_URL,
    },
    CARE_AGENT: {
        "id": CARE_AGENT,
        "label": "Care Coordination Agent",
        "blurb": "Clinical history, guidelines and treatment",
        "accent": "#8b5cf6",
        "env_var": "CARE_AGENT_URL",
        "default_url": _DEFAULT_CARE_AGENT_URL,
    },
}

DEFAULT_AGENT = INSURANCE_AGENT


def is_known(agent_id: str) -> bool:
    return agent_id in AGENTS


def base_url(agent_id: str) -> str:
    """Where this agent's playground publishes its API, without a trailing slash.

    Raises `KeyError` for an unknown agent. Callers must validate first: answering as
    the wrong agent is worse than erroring, because the reply would be attributed to an
    agent that never said it.
    """
    agent = AGENTS[agent_id]
    url = os.getenv(agent["env_var"]) or agent["default_url"]
    return url.rstrip("/")


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
