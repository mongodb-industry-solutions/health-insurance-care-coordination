"""Agent state definition for Care Coordination - Health Insurance.

Keep this JSON-serializable — messages only, never clients, handles or closures.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State for the clinical assessment workflow (Steps 3-7)."""

    messages: Annotated[list[AnyMessage], add_messages]
