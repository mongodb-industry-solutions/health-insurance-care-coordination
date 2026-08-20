"""Direct data access for the care-coordination tools.

This module is what `backend/*/routes.py` used to be. The tools no longer call a
backend over HTTP; they call the vendored services in `data/` in-process and this
module holds the two things the FastAPI layer was quietly providing:

* **Service lifetime.** A `MongoClient` owns a connection pool and is meant to be
  created once per process. `data.db.mdb.get_connector` is `lru_cache`d, and the
  service accessors here are too, so every tool call reuses one pool instead of
  opening its own.

* **Response shaping.** FastAPI serialized every response through its
  `response_model` with `by_alias=True`. Four of the models the tools return carry
  field aliases (`AuditTrace` has 8, `Member` 9, plus `MemberClinicalContext` and
  `GuidelineResponse`), so dumping without aliases would silently rename keys the
  tool docstrings tell the model to read — `memberId` would become `member_id`.
  `respond()` reproduces the old behaviour exactly. `by_alias=True` is not
  optional.

Errors are returned as JSON, never raised: a tool's return value goes to the
model, so a stack trace would be lost and an exception would abort the turn.
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
from .data.guidelines.service import GuidelineService
from .data.members.service import MemberService


def _connector():
    """The process-wide connector, with a legible failure for missing config.

    `MONGODB_URI` is injected by the platform but `DATABASE_NAME` is not — the SDK
    only scopes its own store database (`mdb_store`, see
    `runner_shared.db_config`). Unset, `MongoDBConnector` would do
    `client[None]` and fail deep in pymongo on the first query rather than here.
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
def guidelines() -> GuidelineService:
    return GuidelineService(_connector())


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
            {"error": f"Response did not match {model.__name__}", "detail": e.errors(include_url=False)}
        )


def error(message: str) -> str:
    """A tool-level failure, in the shape the tools have always returned."""
    return json.dumps({"error": message})
