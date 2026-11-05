"""Direct data access for the care-coordination tools.

The tools call the services in `data/` in-process. This module holds the two things the
tools need from it:

* **Service lifetime.** A `MongoClient` owns a connection pool and is meant to be created
  once per process, so the service accessors are `lru_cache`d and every tool call reuses
  one pool.

* **Response shaping.** `respond()` serialises with `by_alias=True`. The models carry field
  aliases (`memberId`, `traceId`, `providerId`), so dumping without aliases would silently
  rename keys the tool docstrings tell the model to read. `by_alias=True` is not optional.

Errors are returned as JSON, never raised: a tool's return value goes to the model, so a
stack trace would be lost and an exception would abort the turn.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ValidationError

from .data.clinical import ClinicalService, DispenseRepository, ProfileRepository
from .data.db import clinical_connector, trace_connector
from .data.guidelines import GuidelineRepository, GuidelineService
from .data.trace import ReasoningRepository, TraceRepository, TraceService


@lru_cache(maxsize=1)
def guidelines() -> GuidelineService:
    return GuidelineService(GuidelineRepository(clinical_connector()))


@lru_cache(maxsize=1)
def clinical() -> ClinicalService:
    connector = clinical_connector()
    return ClinicalService(
        ProfileRepository(connector),
        DispenseRepository(connector),
        GuidelineRepository(connector),
    )


@lru_cache(maxsize=1)
def traces() -> TraceService:
    clinical_db = clinical_connector()
    return TraceService(
        TraceRepository(trace_connector()),
        ReasoningRepository(clinical_db),
        ProfileRepository(clinical_db),
    )


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
