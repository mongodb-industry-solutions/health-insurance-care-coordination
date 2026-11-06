"""Direct data access for the insurance tools.

The tools call the services in `data/` in-process. This module holds the things the tools
need from it:

* **Service lifetime.** A `MongoClient` owns a connection pool and is meant to be created
  once per process, so the service accessors are `lru_cache`d and every tool call reuses
  one pool.

* **Response shaping.** `respond()` serialises with `by_alias=True`. The models carry field
  aliases (`memberId`, `traceId`, `planId`), so dumping without aliases would silently
  rename keys the tool docstrings tell the model to read. `by_alias=True` is not optional.

* **Refusal vs. failure.** The services raise `ValueError` where a request is *refused* and
  `LookupError` where a subject is *missing*. The first is load-bearing here: closure and
  claim-status express bounded authority by refusing, so the refusal is a correct answer to
  escalate or report, never a transient error to retry. `refused()` keeps those messages
  distinct from `error()`.

Errors are returned as JSON, never raised: a tool's return value goes to the model, so an
exception would abort the turn and lose the explanation.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ValidationError

from .data.db import Collections, insurance_connector
from .data.insurance import (
    ClaimRepository,
    ClaimService,
    MemberRepository,
    MemberService,
    PlanRepository,
    PlanService,
    PolicyRepository,
    PolicyService,
)
from .data.trace import ReasoningRepository, TraceRepository, TraceService


def build_services(connector):
    """Wire every service onto one connector. Kept separate from the cached accessors so
    the tests can build the same graph over an in-memory database."""
    traces_collection = connector.get_collection(Collections.AUDIT_LOG)
    member_repo = MemberRepository(connector)
    claim_repo = ClaimRepository(connector)
    members = MemberService(member_repo, traces_collection)
    policies = PolicyService(PolicyRepository(connector))
    plans = PlanService(PlanRepository(connector))
    claims = ClaimService(claim_repo, member_repo, traces_collection)
    traces = TraceService(
        TraceRepository(connector),
        ReasoningRepository(connector),
        member_repo,
        members,
        policies,
        plans,
        claim_repo,
    )
    return {
        "members": members,
        "policies": policies,
        "plans": plans,
        "claims": claims,
        "traces": traces,
    }


@lru_cache(maxsize=1)
def _services() -> dict:
    return build_services(insurance_connector())


def members() -> MemberService:
    return _services()["members"]


def policies() -> PolicyService:
    return _services()["policies"]


def plans() -> PlanService:
    return _services()["plans"]


def claims() -> ClaimService:
    return _services()["claims"]


def traces() -> TraceService:
    return _services()["traces"]


def respond(model: type[BaseModel], value: Any) -> str:
    """Serialise a service result through its response model.

    Validation is what makes a service-side field rename fail loudly here instead of
    reaching the model as a silently missing key. A `ValidationError` is a bug in this
    layer, so it is reported as an error rather than masked as data.
    """
    try:
        return json.dumps(model.model_validate(value).model_dump(mode="json", by_alias=True))
    except ValidationError as e:
        return json.dumps(
            {
                "error": f"Response did not match {model.__name__}",
                "detail": e.errors(include_url=False),
            },
            default=str,
        )


def error(message: str) -> str:
    """A tool-level failure."""
    return json.dumps({"error": message})


def refused(message: str) -> str:
    """A request the service declined on policy grounds. Distinct from `error()` on
    purpose: a refusal from a closure or claim-status tool means the bounded-authority
    guardrail fired, and the answer is to escalate or report it, not to retry."""
    return json.dumps({"error": message})
