"""care-coordination Magenta app."""

from __future__ import annotations

import logging
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from magenta_sdklanggraph import App

from agent_care_coordination.llm import build_llm
from agent_care_coordination.state import HelloWorldState
from agent_care_coordination.system_message import (
    PATHWAY_PROMPT,
    VERIFICATION_PROMPT,
    DECISION_PROMPT,
)
from agent_care_coordination.tools import register

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)
load_dotenv()

app = App(app_name="care-coordination")

register(app)


@app.entrypoint
def build_agent() -> CompiledStateGraph:
    """Build the LangGraph agent."""
    logger.info("Building care-coordination graph")
    llm_config = getattr(app, "llm_config", None)
    runtime_llm = app.llm(
        build_llm(
            provider=getattr(llm_config, "provider", None),
            model=getattr(llm_config, "model", None),
            temperature=0,
        )
    )
    tools = app.get_tools()
    llm_with_tools = runtime_llm.bind_tools(app.get_tool_schemas())

    def _run_agent(prompt: str, state: HelloWorldState) -> dict:
        """Invoke the LLM for one agent node with its own system prompt.

        The system prompt is applied per-invocation and never stored in state, so
        each node sees the full shared history under its own persona. Any stray
        SystemMessage in history is dropped so the two prompts never collide.
        """
        history = [m for m in state["messages"] if not isinstance(m, SystemMessage)]
        response = llm_with_tools.invoke([SystemMessage(content=prompt)] + history)
        response = app.validate_llm_response(response)
        return {"messages": [response]}

    def _has_tool_calls(state: HelloWorldState) -> bool:
        last = state["messages"][-1]
        return bool(getattr(last, "tool_calls", None))

    # --- Node 1: pathway agent (assembles the case) --------------------------
    def pathway_node(state: HelloWorldState) -> dict:
        return _run_agent(PATHWAY_PROMPT, state)

    def pathway_route(state: HelloWorldState) -> Literal["tools", "verify"]:
        # Loop through its own tools until done, then hand off to verification.
        return "tools" if _has_tool_calls(state) else "verify"

    # --- Node 2: verification agent (independently reviews the synthesis) ----
    def verification_node(state: HelloWorldState) -> dict:
        return _run_agent(VERIFICATION_PROMPT, state)

    def verification_route(state: HelloWorldState) -> Literal["tools", "decide"]:
        # Loop through its own tools until done, then hand off to the decision step.
        return "tools" if _has_tool_calls(state) else "decide"

    # --- Node 3: decision (files + processes + notifies; never closes a denial) --
    def decision_node(state: HelloWorldState) -> dict:
        return _run_agent(DECISION_PROMPT, state)

    def decision_route(state: HelloWorldState) -> Literal["tools", "end"]:
        return "tools" if _has_tool_calls(state) else "end"

    builder = StateGraph(HelloWorldState)
    builder.add_node("pathway", pathway_node)
    builder.add_node("pathway_tools", ToolNode(tools))
    builder.add_node("verification", verification_node)
    builder.add_node("verification_tools", ToolNode(tools))
    builder.add_node("decision", decision_node)
    builder.add_node("decision_tools", ToolNode(tools))

    builder.add_edge(START, "pathway")
    builder.add_conditional_edges(
        "pathway", pathway_route, {"tools": "pathway_tools", "verify": "verification"}
    )
    builder.add_edge("pathway_tools", "pathway")
    builder.add_conditional_edges(
        "verification", verification_route,
        {"tools": "verification_tools", "decide": "decision"},
    )
    builder.add_edge("verification_tools", "verification")
    builder.add_conditional_edges(
        "decision", decision_route, {"tools": "decision_tools", "end": END}
    )
    builder.add_edge("decision_tools", "decision")
    return builder.compile(checkpointer=app.checkpointer())


def main() -> None:
    """Run the hello-world agent."""
    app.run()


if __name__ == "__main__":
    main()
