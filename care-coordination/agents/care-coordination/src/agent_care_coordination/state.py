"""Graph state for the care-coordination agent.

Keep this JSON-serializable — messages and scalar case keys only, never clients,
handles or closures.
"""

from __future__ import annotations

from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class _AgentStateOptional(TypedDict, total=False):
    """Optional fields, so LangGraph's partial state updates type-check."""

    user_id: Optional[str]
    session_id: Optional[str]


class AgentState(_AgentStateOptional):
    """State for the clinical assessment workflow (Steps 3-7)."""

    messages: Annotated[list[AnyMessage], add_messages]
