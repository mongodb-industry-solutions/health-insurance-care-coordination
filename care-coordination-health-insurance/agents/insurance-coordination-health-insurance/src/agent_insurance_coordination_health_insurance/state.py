"""Agent state definition for Insurance Coordination - Health Insurance.

Keep this JSON-serializable — messages only, never clients, handles or closures.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State for the administrative workflow (Steps 0-2 and 8-9)."""

    messages: Annotated[list[AnyMessage], add_messages]
