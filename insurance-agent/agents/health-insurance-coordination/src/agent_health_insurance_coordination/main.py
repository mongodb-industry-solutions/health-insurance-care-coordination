"""health-insurance-coordination Magenta app.

The Insurance Agent's half of the prior-authorization process: it opens the case,
runs the two administrative gates, and — once a clinical recommendation exists —
routes and closes it under bounded authority.

The agent holds no database driver and no models shared with the backend. Every
domain read and write is an HTTP call to the FastAPI service (`BACKEND_URL`),
which owns the data in `health_insurance_agent` and enforces the authority rules
deterministically, server-side.

The platform launches this code in supported runtime roles:
    RUNNER_MODE=aer            -> Full LangGraph execution
    RUNNER_MODE=tool           -> Tool function execution
    RUNNER_MODE=memory-server  -> Long-term memory service
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from typing import Literal, Optional

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from magenta_sdklanggraph import App

from agent_health_insurance_coordination.llm import build_llm
from agent_health_insurance_coordination.state import AgentState
from agent_health_insurance_coordination.system_message import SYSTEM_PROMPT
from agent_health_insurance_coordination.tools import register

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
load_dotenv()

APP_NAME = "health-insurance-coordination"

app = App(app_name=APP_NAME)

register(app)


@app.entrypoint
def build_agent(llm: Optional[BaseChatModel] = None) -> CompiledStateGraph:
    """Build the LangGraph agent.

    Args:
        llm: LLM to use. Defaults to app.llm() when None. Pass an explicit LLM
            (e.g. a FakeLLM) for testing without real API calls.
    """
    logger.info("Building health-insurance-coordination graph")

    if llm is None:
        llm_config = getattr(app, "llm_config", None)
        llm = app.llm(
            build_llm(
                provider=getattr(llm_config, "provider", None),
                model=getattr(llm_config, "model", None),
                temperature=0,
            )
        )

    tools = app.get_tools()
    llm_with_tools = llm.bind_tools(app.get_tool_schemas())

    def agent_node(state: AgentState) -> dict:
        user_id = state.get("user_id", "")

        # Eligibility turns on the date of service, so state today's date rather
        # than letting the model assume it.
        prompt = f"{SYSTEM_PROMPT}\n\n## Current session\nToday's date is {date.today().isoformat()}."
        if user_id:
            prompt += f" You are speaking with user_id: {user_id}."

        history = [m for m in state["messages"] if not isinstance(m, SystemMessage)]
        response = llm_with_tools.invoke([SystemMessage(content=prompt)] + history)
        response = app.validate_llm_response(response)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> Literal["tools", "end"]:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else "end"

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    builder.add_edge("tools", "agent")

    # The checkpointer needs MongoDB. If it is unreachable the agent should still
    # answer single-turn requests rather than fail to build, which would turn
    # every request into a 500.
    try:
        checkpointer = app.checkpointer()
    except Exception as e:
        logger.warning(
            f"Failed to construct checkpointer ({e}) — running without conversation persistence."
        )
        checkpointer = None

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("✅ Agent graph compiled")
    return graph


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info(f"🚀 Starting {APP_NAME} (Runner SDK)")
    logger.info("=" * 60)
    app.run()


if __name__ == "__main__":
    main()
