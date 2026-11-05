"""care-coordination Magenta app.

The Care-Coordination Agent's half of the prior-authorization process: Steps 3-7,
the clinical assessment. It picks up a case the Insurance Agent already opened,
reasons over the member's record and the applicable guideline, and records a
recommendation on the decision trace. It never routes or closes a case.

Every domain read and write goes straight to MongoDB in-process, through the
vendored data layer in `data/` (services and repositories lifted from the backend,
minus its HTTP routes). `data_access` holds the service instances and reproduces
the response shaping the FastAPI layer used to do. The authority rules still live
in that service code and are still applied deterministically — what went away is
the network hop, not the enforcement.

Requires `MONGODB_URI` (platform-injected) and `DATABASE_NAME` (declared in
agent.yaml). The application database is separate from the platform's own store.

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
# from magenta_sdklanggraph import App
from agent_engine_sdk_langgraph import App

from agent_care_coordination.llm import build_llm
from agent_care_coordination.state import AgentState
from agent_care_coordination.system_message import SYSTEM_PROMPT
from agent_care_coordination.tools import register

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
load_dotenv()

APP_NAME = "care-coordination"

app = App(app_name=APP_NAME)

register(app)


@app.entrypoint
def build_agent(llm: Optional[BaseChatModel] = None) -> CompiledStateGraph:
    """Build the LangGraph agent.

    Args:
        llm: LLM to use. Defaults to app.llm() when None. Pass an explicit LLM
            (e.g. a FakeLLM) for testing without real API calls.
    """
    logger.info("Building care-coordination graph")

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

        # Trial durations are read against today, so state the date rather than
        # letting the model assume it.
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

    def finish_node(state: AgentState) -> dict:
        """Release this session's compute instead of holding it to the idle TTL.

        This agent takes one turn per case — Steps 3-7, the clinical assessment — and
        is never resumed: the insurance agent's routing turn is a separate session on
        a separate app. Holding the AER and tool pods after the recommendation is
        recorded only competes for capacity with the turns either side of it.

        `END` is a sentinel rather than a node, so this exists to give the terminal
        branch somewhere to run. It changes no state.

        Safe outside an agent run — the SDK answers UNAVAILABLE rather than raising,
        so local scripts and tests are unaffected.

        If this workflow ever passes `session_id` to continue a conversation across
        turns, this node has to go: finishing the session releases exactly the pods a
        continued turn would need.

        `finish_session` is only present in newer magenta_sdklanggraph builds, and
        this app's lock predates it — hence the lookup rather than a direct call.
        Warn rather than fail: an old SDK should cost the early release, not the run.
        Re-lock the SDK and the release starts happening with no code change.
        """
        finish = getattr(app, "finish_session", None)
        if finish is None:
            logger.warning(
                "app.finish_session() unavailable in this magenta_sdklanggraph build; "
                "session compute will be held until the idle reservation expires."
            )
            return {}
        logger.info("session finish requested: %s", finish())
        return {}

    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(tools))
    builder.add_node("finish", finish_node)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": "finish"})
    builder.add_edge("tools", "agent")
    builder.add_edge("finish", END)

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


def main() -> None:
    """Main entry point."""
    logger.info("=" * 60)
    logger.info(f"🚀 Starting {APP_NAME} (Runner SDK)")
    logger.info("=" * 60)
    app.run()


if __name__ == "__main__":
    main()
