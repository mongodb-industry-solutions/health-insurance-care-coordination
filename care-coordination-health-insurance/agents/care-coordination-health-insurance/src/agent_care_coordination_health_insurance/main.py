"""Care Coordination - Health Insurance.

The Care-Coordination Agent's half of the prior-authorization process: Steps 3-7, the
clinical assessment. It picks up a case the Insurance Agent already opened and cleared
administratively, reasons over the member's clinical record and the applicable
guideline, and records a recommendation on the shared authorization trace. It never
routes or closes a case.

It works with clinical data only. Eligibility, plans, policies and claims belong to the
Insurance Agent and are neither read nor written here; the shared trace is the only
object the two agents have in common.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from agent_engine_sdk_langgraph import App
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from agent_care_coordination_health_insurance.llm import build_llm
from agent_care_coordination_health_insurance.state import AgentState
from agent_care_coordination_health_insurance.system_message import SYSTEM_PROMPT
from agent_care_coordination_health_insurance.tools import register

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)
load_dotenv()

app = App(app_name="Care Coordination - Health Insurance")

register(app)


@app.entrypoint
def build_agent() -> CompiledStateGraph:
    """Build the LangGraph agent."""
    logger.info("Building Care Coordination - Health Insurance graph")
    runtime_llm = app.llm(build_llm(temperature=0))
    tools = app.get_tools()
    llm_with_tools = runtime_llm.bind_tools(app.get_tool_schemas())

    def agent_node(state: AgentState) -> dict:
        # Trial durations are read against today, so state the date rather than letting
        # the model assume it.
        prompt = f"{SYSTEM_PROMPT}\n\n## Current session\nToday's date is {date.today().isoformat()}."

        history = [m for m in state["messages"] if not isinstance(m, SystemMessage)]
        response = llm_with_tools.invoke([SystemMessage(content=prompt)] + history)
        response = app.validate_llm_response(response)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> Literal["tools", "end"]:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else "end"

    def finish_node(state: AgentState) -> dict:
        """Release this session's compute instead of holding it to the idle TTL.

        This agent takes one turn per case — Steps 3-7 — and is never resumed: the
        insurance agent's routing turn is a separate session. Holding the sandboxes after
        the recommendation is recorded only competes for capacity with the turns either
        side of it. `END` is a sentinel rather than a node, so this exists to give the
        terminal branch somewhere to run. It changes no state.

        `finish_session` returns UNAVAILABLE rather than raising outside an agent run.
        If this workflow ever continues a conversation across turns by passing a
        `session_id`, this node has to go: finishing the session releases exactly the
        sandboxes a continued turn would need.
        """
        logger.info("session finish requested: %s", app.finish_session())
        return {}

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(tools))
    builder.add_node("finish", finish_node)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": "finish"})
    builder.add_edge("tools", "agent")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=app.checkpointer())


def main() -> None:
    """Run the agent."""
    app.run()


if __name__ == "__main__":
    main()
