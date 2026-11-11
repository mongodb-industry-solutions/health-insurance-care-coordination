"""The two agents the chat can talk to.

Deliberately the *same* agents the authorization workflow drives, reached the same way
(`shared/aae_client.py`), so the chat and the workflow can never drift onto different
deployments or credentials. This module is only the registry the agent picker reads.

`label` and `blurb` are display-only and travel to the browser; nothing here is secret, which
is why this whole registry can be served by GET /api/chat/agents.
"""

from shared.aae_client import CARE_AGENT, INSURANCE_AGENT

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


def public_list() -> list[dict]:
    """The registry as the agent picker needs it. No URLs and no credentials: the browser
    never calls an agent directly, it always goes through this backend."""
    return [
        {
            "id": a["id"],
            "label": a["label"],
            "blurb": a["blurb"],
            "accent": a["accent"],
        }
        for a in AGENTS.values()
    ]
