"""Agent state definition for care-coordination."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class HelloWorldState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    # Set by the triage node: "workflow" runs the prior-auth pipeline
    # (pathway -> verification -> decision); "question" answers read-only and
    # stops. Absent until triage runs.
    mode: str
