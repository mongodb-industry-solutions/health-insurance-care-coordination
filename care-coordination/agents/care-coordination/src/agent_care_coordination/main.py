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
    ANSWER_PROMPT,
    DECISION_PROMPT,
    PATHWAY_PROMPT,
    TRIAGE_PROMPT,
    VERIFICATION_PROMPT,
)
from agent_care_coordination.tools import register

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)
load_dotenv()

app = App(app_name="care-coordination")

register(app)

# Tools the read-only answer branch may use. Anything that writes to a member's
# record — filing, processing, notifying, resolving a gap — is deliberately absent,
# so a question cannot mutate state even if the model tries.
READ_ONLY_TOOLS = frozenset(
    {
        "get_current_date",
        "recall_user_info",
        "get_member_clinical_context",
        "get_applicable_guideline",
        "find_comparable_claims",
        "detect_refill_gaps",
        "get_member_authorizations",
    }
)


def _tool_name(tool: object) -> str | None:
    """Tool name from either a tool object or a raw schema dict."""
    if isinstance(tool, dict):
        return tool.get("name")
    return getattr(tool, "name", None)


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
    schemas = app.get_tool_schemas()
    read_only_tools = [t for t in tools if _tool_name(t) in READ_ONLY_TOOLS]
    read_only_schemas = [s for s in schemas if _tool_name(s) in READ_ONLY_TOOLS]

    llm_with_tools = runtime_llm.bind_tools(schemas)
    llm_read_only = runtime_llm.bind_tools(read_only_schemas)

    def _history(state: HelloWorldState) -> list:
        """Shared conversation history with any stray SystemMessage removed, so a
        node's own persona prompt is the only system prompt it sees."""
        return [m for m in state["messages"] if not isinstance(m, SystemMessage)]

    def _run_agent(prompt: str, state: HelloWorldState, llm=None) -> dict:
        """Invoke the LLM for one agent node with its own system prompt.

        The system prompt is applied per-invocation and never stored in state, so
        each node sees the full shared history under its own persona. `llm`
        defaults to the full tool set; the answer node passes the read-only one.
        """
        response = (llm or llm_with_tools).invoke(
            [SystemMessage(content=prompt)] + _history(state)
        )
        response = app.validate_llm_response(response)
        return {"messages": [response]}

    def _has_tool_calls(state: HelloWorldState) -> bool:
        last = state["messages"][-1]
        return bool(getattr(last, "tool_calls", None))

    # --- Node 0: triage (question vs. authorization workflow) ----------------
    def triage_node(state: HelloWorldState) -> dict:
        """Classify intent WITHOUT tools and WITHOUT adding to the transcript.

        Returns only `mode`, so the classification never appears as a message the
        user sees or that a later persona has to reason around.
        """
        verdict = runtime_llm.invoke(
            [SystemMessage(content=TRIAGE_PROMPT)] + _history(state)
        )
        text = str(getattr(verdict, "content", "") or "").upper()
        # Default to the read-only branch: filing an authorization writes to a
        # member's record, so it happens only on an unambiguous WORKFLOW verdict.
        mode = "workflow" if "WORKFLOW" in text else "question"
        logger.info("Triage classified request as: %s", mode)
        return {"mode": mode}

    def triage_route(state: HelloWorldState) -> Literal["answer", "pathway"]:
        return "pathway" if state.get("mode") == "workflow" else "answer"

    # --- Node 0a: answer (read-only Q&A; never reaches the decision node) ----
    def answer_node(state: HelloWorldState) -> dict:
        return _run_agent(ANSWER_PROMPT, state, llm=llm_read_only)

    def answer_route(state: HelloWorldState) -> Literal["tools", "end"]:
        return "tools" if _has_tool_calls(state) else "end"

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
    builder.add_node("triage", triage_node)
    builder.add_node("answer", answer_node)
    builder.add_node("answer_tools", ToolNode(read_only_tools))
    builder.add_node("pathway", pathway_node)
    builder.add_node("pathway_tools", ToolNode(tools))
    builder.add_node("verification", verification_node)
    builder.add_node("verification_tools", ToolNode(tools))
    builder.add_node("decision", decision_node)
    builder.add_node("decision_tools", ToolNode(tools))

    builder.add_edge(START, "triage")
    builder.add_conditional_edges(
        "triage", triage_route, {"answer": "answer", "pathway": "pathway"}
    )
    builder.add_conditional_edges(
        "answer", answer_route, {"tools": "answer_tools", "end": END}
    )
    builder.add_edge("answer_tools", "answer")
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
