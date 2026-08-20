"""Direct data access for the insurance-coordination tools.

This module is what `backend/*/routes.py` used to be. The tools no longer call a
backend over HTTP; they call the vendored services in `data/` in-process and this
module holds the things the FastAPI layer was quietly providing:

* **Service lifetime.** A `MongoClient` owns a connection pool and is meant to be
  created once per process. `data.db.mdb.get_connector` is `lru_cache`d, and the
  service accessors here are too, so every tool call reuses one pool.

* **Response shaping.** FastAPI serialized every response through its
  `response_model` with `by_alias=True`. Nine of the models these tools return
  carry field aliases — `Claim` has 16, `Policy` 10, `Plan` 9, `Member` 9,
  `AuditTrace` 8, `RoutingDecisionResponse` 8 — so dumping without aliases would
  silently rename keys the tool docstrings tell the model to read.
  `by_alias=True` is not optional.

* **Refusal vs. failure.** The services raise `ValueError` where a request is
  *refused* and `LookupError` where a subject is *missing*; the routes mapped these
  to 400 and 404. That distinction is load-bearing here in a way it was not for the
  care-coordination agent: `close_administrative`, `close_authorization` and
  `update_claim_status` express the bounded-authority rules by refusing, and the
  refusal is the correct answer rather than a transient error. `refused()` keeps
  those messages distinct from `error()` so the model does not retry a decision it
  is not permitted to make.

Errors are returned as JSON, never raised: a tool's return value goes to the model,
so an exception would abort the turn and lose the explanation.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ValidationError

from .data.audit.service import AuditService
from .data.claims.service import ClaimService
from .data.db.mdb import get_connector
from .data.members.service import MemberService
from .data.plans.service import PlanService
from .data.policies.service import PolicyService


def _connector():
    """The process-wide connector, with a legible failure for missing config.

    `MONGODB_URI` is injected by the platform but `DATABASE_NAME` is not — the SDK
    only scopes its own store database (`mdb_store`, see
    `runner_shared.db_config`). Unset, `MongoDBConnector` would do `client[None]`
    and fail deep in pymongo on the first query rather than here.

    The `RuntimeError` is raised lazily, on the first service call rather than at
    import, so a misconfigured tool pod still starts and reports the problem through
    the tool result. Every tool therefore catches `RuntimeError` alongside
    `PyMongoError`: raising out of a tool body would abort the turn and lose this
    message, which is the one thing that makes the misconfiguration diagnosable.

    `lru_cache` does not memoize exceptions, so a later call retries once the
    variable is present.
    """
    if not os.environ.get("DATABASE_NAME"):
        raise RuntimeError(
            "DATABASE_NAME is not set. The tools read the application database "
            "directly; declare it in agent.yaml required_secrets and .env."
        )
    return get_connector()


@lru_cache(maxsize=1)
def members() -> MemberService:
    return MemberService(_connector())


@lru_cache(maxsize=1)
def policies() -> PolicyService:
    return PolicyService(_connector())


@lru_cache(maxsize=1)
def plans() -> PlanService:
    return PlanService(_connector())


@lru_cache(maxsize=1)
def claims() -> ClaimService:
    return ClaimService(_connector())


@lru_cache(maxsize=1)
def audit() -> AuditService:
    return AuditService(_connector())


def respond(model: type[BaseModel], value: Any) -> str:
    """Serialize a service result the way FastAPI's `response_model` did.

    Validation is what makes a service-side field rename fail loudly here instead
    of reaching the model as a silently missing key. A `ValidationError` is a bug
    in this layer, so it is reported as an error rather than masked as data.
    """
    try:
        return json.dumps(model.model_validate(value).model_dump(mode="json", by_alias=True))
    except ValidationError as e:
        return json.dumps(
            {
                "error": f"Response did not match {model.__name__}",
                "detail": e.errors(include_url=False),
            }
        )


def error(message: str) -> str:
    """A tool-level failure, in the shape the tools have always returned."""
    return json.dumps({"error": message})


def refused(message: str) -> str:
    """A request the service declined on policy grounds — the former HTTP 400.

    Distinct from `error()` on purpose. A refusal from a closure or claim-status
    tool means the bounded-authority guardrail fired: the answer is to escalate,
    not to retry.
    """
    return json.dumps({"error": message})
