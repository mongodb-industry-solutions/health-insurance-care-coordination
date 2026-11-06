"""Check, from this machine, that the backend can reach the deployed agents.

    cd backend
    python scripts/check_agents.py             # configuration + access token (no agent is run)
    python scripts/check_agents.py --invoke    # also sends one harmless message to each agent

It reads the same environment (and `.env`) the backend does. It prints which variables are set,
never their values, and never a token. `--invoke` runs a real turn on each agent (a few seconds
of model time each): the message asks for a one-word reply and tells the agent to use no tools,
so it writes nothing.

Exit code 0 only if everything asked for worked.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from shared.aae_client import (  # noqa: E402
    AgentEngineConfigurationError,
    AgentEngineError,
    CARE_AGENT,
    ENV_PREFIX,
    INSURANCE_AGENT,
    get_client,
)

PING = "Reply with the single word: pong. Do not call any tools and do not record anything."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--invoke", action="store_true", help="also send one harmless message to each agent")
    args = parser.parse_args()

    client = get_client()
    ok = True

    print("configuration")
    for name in ("AAE_CLIENT_ID", "AAE_CLIENT_SECRET", "AAE_PROJECT_ID"):
        print(f"  {name:32} {'set' if client._get(name) else 'MISSING'}")
    for agent in (INSURANCE_AGENT, CARE_AGENT):
        prefix = ENV_PREFIX[agent]
        project, workspace, missing = client._target(agent)
        print(f"  {prefix}_PROJECT_ID".ljust(34), project or "MISSING")
        print(f"  {prefix}_WORKSPACE_ID".ljust(34), workspace or "MISSING")
    print(f"  base url                         {client.base_url}")
    print(f"  api contract                     {client.accept}")
    try:
        client.validate()
    except AgentEngineConfigurationError as e:
        print(f"\nNOT CONFIGURED: {e}")
        return 1

    print("\naccess token")
    try:
        client.get_token()
        print("  OK: the service account exchanged for a token")
    except AgentEngineError as e:
        print(f"  FAILED: {e}")
        return 1

    print("\nagent endpoints")
    for agent in (INSURANCE_AGENT, CARE_AGENT):
        print(f"  {agent:20} {client.url(agent, 'invoke')}")

    if not args.invoke:
        print("\nRe-run with --invoke to send a message to each agent.")
        return 0

    print("\ninvoke")
    for agent in (INSURANCE_AGENT, CARE_AGENT):
        started = time.monotonic()
        try:
            result = client.invoke(agent, PING, timeout=300)
        except AgentEngineError as e:
            print(f"  {agent:20} FAILED: {e}")
            ok = False
            continue
        elapsed = time.monotonic() - started
        print(f"  {agent:20} {'OK' if result['ok'] else 'NOT COMPLETED'} in {elapsed:.1f}s  "
              f"status={result['status']}  execution_id={result['execution_id']}  "
              f"session_id={result['session_id']}")
        reply = str(result.get("response") or "").strip().replace("\n", " ")
        print(f"  {'':20} reply: {reply[:160]}")
        if not result["ok"]:
            print(f"  {'':20} {result.get('error')}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
