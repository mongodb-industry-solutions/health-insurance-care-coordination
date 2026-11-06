# Demo Template: Python Backend

Python backend section built using [FastAPI](https://fastapi.tiangolo.com/). The backend is managed using uv for dependency management, offering a RESTful API.

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
  - [Backend Setup](#backend-setup)
- [Running the Application](#running-the-application)
- [API Documentation](#api-documentation)
- [Contributing](#contributing)
- [License](#license)

## Features

- Python backend with a RESTful API powered by FastAPI
- Dependency management with uv ([More info](https://docs.astral.sh/uv/))
- Easy setup and configuration

## Prerequisites

Before you begin, ensure you have met the following requirements:

- Python 3.13 (but less than 3.14)
- uv (install via [uv's official documentation](https://docs.astral.sh/uv/getting-started/installation/))

For complete setup instructions, including how to create a new repository and clone it, please refer to the [parent README](../README.md).

## Getting Started

Follow these steps to set up the backend project locally. For detailed instructions on creating a new repository and using GitHub Desktop, please refer to the [parent README](../README.md).

### Backend Setup

1. (Optional) Set your project description and author information in the `pyproject.toml` file:
   ```toml
   description = "Your Description"
   authors = ["Your Name <you@example.com>"]
2. Open the project in your preferred IDE (the standard for the team is Visual Studio Code).
3. Open the Terminal within Visual Studio Code.
4. Ensure you are in the root project directory where the `makefile` is located.
5. Execute the following commands:
  - uv initialization
    ````bash
    make uv_init
    ````
  - uv sync
    ````bash
    make uv_sync
    ````
6. Verify that the `.venv` folder has been generated within the `/backend` directory.

## Running the Application

After setting up the backend dependencies, you can run the development server:

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Start the FastAPI development server:
   ```bash
   uv run uvicorn main:app --host 0.0.0.0 --port 8000
   ```

3. The backend API will be accessible at http://localhost:8000

**Note**: If port 8000 is already in use (e.g., by Docker containers), either stop the containers with `make clean` or use a different port like `--port 8001`.

## Data: two databases

The data is split across two databases on one cluster, and the backend is the only component
that holds both (each agent holds one). Set, in `.env` or the deployment config:

| Variable | Meaning |
|---|---|
| `MONGODB_URI` | one connection string for both |
| `INSURANCE_DATABASE` | members, policies, plans, claims, the shared trace (`audit_log`), `admin_reasoning`. Falls back to `DATABASE_NAME` so an existing single-database deployment keeps its insurance routes. |
| `CLINICAL_DATABASE` | clinical profiles, dispense history, guidelines, `clinical_reasoning` |

A missing name is a `503` that names the variable, on the routes that need it. Create the
indexes in both with `python -m db.indexes`, and load the demo data with
`python -m seed.seed_data [--reset]` (the same code as `POST /reset-demo`).

## Calling the agents

Both agents are deployed on Atlas Agent Engine and reached the same way by the workflow and the chat
(`shared/aae_client.py`): an OAuth token from a service account, then
`POST https://agentengine.mongodb.com/api/v1/projects/{project}/workspaces/{workspace}/invoke`
(`invokeStream` for the chat), with the API contract pinned in `Accept`. There is no local mode.

| Variable | Meaning |
|---|---|
| `AGENT_INVOKE_MODE` | `dry_run` (the default: records what it would send and calls nothing) or anything else = call the deployed agents |
| `AAE_CLIENT_ID`, `AAE_CLIENT_SECRET` | the service account (project role `PROJECT_OWNER`, which invoking requires) |
| `AAE_PROJECT_ID` | the project, shared by both agents |
| `INSURANCE_AGENT_WORKSPACE_ID`, `CARE_AGENT_WORKSPACE_ID` | one workspace per agent |
| `INSURANCE_AGENT_PROJECT_ID`, `CARE_AGENT_PROJECT_ID` | optional: override `AAE_PROJECT_ID` for one agent |
| `AGENT_INVOKE_TIMEOUT` | seconds to wait for one blocking turn (default 900) |
| `AGENT_TURN_GRACE_SECONDS` | after a turn times out (the platform's `AGENT_TIMEOUT` 504, or ours), keep reading the case this long for the agent's work to land, then continue (default 600; `0` = fail immediately) |
| `AGENT_GRACE_POLL_SECONDS` | how often to read it during that wait (default 5) |
| `AAE_BASE_URL`, `AAE_API_ACCEPT`, `AAE_POOL_RETRIES` | optional: platform URL, pinned API version, retries on "pool full" (default 3) |

A missing variable is a `503` naming every one that is missing (never a value). Check the setup from this
machine, without running the app:

```bash
cd backend
python scripts/check_agents.py             # configuration + access token
python scripts/check_agents.py --invoke    # also sends one harmless message to each agent
```

## Layout

Grouped by which database a package touches, not by data object:

```
db/          two connectors (insurance, clinical) and the index script
shared/      collection names, the summary derivation, and the Agent Engine client
insurance/   members, policies, plans, claims, admin_reasoning   -> insurance database only
clinical/    profiles, clinical_reasoning                        -> clinical database only
traces/      the shared authorization envelope and its stage machine (names `traces`, not
             `trace`, so it cannot shadow the standard-library module)
views/       composed reads: the combined member, traces with their step text, the director's
             queue and brief. The only place the two sides meet for the UI.
workflow/    start / live progress / the medical director's decision, and the clinical sync
admin/ seed/ demo seed and reset, from the JSON in seed/fixtures/
chat/        free-form chat with the two agents
```

`insurance/` and `clinical/` never import each other; `traces/` imports neither. Only
`views/`, `workflow/` and `admin/` may import both. `tests/test_boundaries.py` enforces it.
Route paths are unchanged, so the frontend does not notice the split.

## Tests

No pytest and no extra dependencies in `pyproject.toml`; each file is a script that uses
in-memory MongoDB and runs the real agents' data-layer code against it:

```bash
cd backend
uv run --with mongomock --with httpx python tests/test_backend.py        # routes, workflow, director, watcher
uv run --with mongomock --with httpx python tests/test_aae_transport.py  # the agent transport, against a fake platform
uv run python tests/test_boundaries.py                                  # import rules
uv run --with mongomock python tests/test_seed_fixtures.py              # fixtures + agent contract
```

See [`docs/UI_CHANGES.md`](docs/UI_CHANGES.md) for what the frontend sees, and
[`docs/FOLLOW_UPS.md`](docs/FOLLOW_UPS.md) for what is deliberately left open.
