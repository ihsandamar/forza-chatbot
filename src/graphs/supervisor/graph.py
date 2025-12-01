"""
Supervisor Graph - Multi-agent supervisor with routing and chat agents.
Routes requests between agents using handoff pattern.
"""
import logging
from typing import Optional
from langgraph.graph import StateGraph, START, END
from langgraph.graph import MessagesState
from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda

from src.models.llm import LLM
from src.graphs.base.base_graph import BaseGraph
from src.graphs.base.graph_config import GraphConfig
from src.graphs.base.graph_metadata import (
    GraphMetadata,
    GraphCapability,
    InputSpec,
    OutputSpec,
)
from src.graphs.registry import register_graph
from src.graphs.chat.graph import ChatGraph
from src.graphs.routing.graph import RoutingGraph
from src.graphs.forza_routing_graph import VegaforzaNavigationGraph
from src.graphs.supervisor.prompts import SUPERVISOR_SYSTEM_PROMPT
from src.graphs.supervisor.tools import (
    get_current_time,
    get_supervisor_status,
    assign_to_chat_agent,
    assign_to_routing_agent
)

logger = logging.getLogger(__name__)


def handle_routing_node(routing_agent):
    """
    Wrapper for routing agent to ensure output is properly converted to MessagesState format.

    Routing agent returns NavigationState but supervisor expects MessagesState.
    This wrapper ensures navigation_output is preserved in the state.
    """
    async def wrapped_routing(state: MessagesState) -> MessagesState:
        logger.info("[SUPERVISOR] Invoking routing agent...")

        try:
            # Invoke routing agent
            routing_output = await routing_agent.ainvoke(state)
            logger.debug(f"[SUPERVISOR] Routing output type: {type(routing_output)}")
            logger.debug(f"[SUPERVISOR] Routing output keys: {list(routing_output.keys()) if hasattr(routing_output, 'keys') else 'N/A'}")

            # Ensure navigation_output is preserved in state
            if isinstance(routing_output, dict):
                # Copy navigation_output to state for next node to process
                if "navigation_output" in routing_output:
                    state["navigation_output"] = routing_output.get("navigation_output")
                    logger.info("[SUPERVISOR] Preserved navigation_output in state")

                # Merge messages if present
                if "messages" in routing_output:
                    state["messages"] = routing_output.get("messages")
                    logger.debug("[SUPERVISOR] Updated messages from routing output")

            return state

        except Exception as e:
            logger.error(f"[SUPERVISOR] Error in routing agent: {e}", exc_info=True)
            raise

    return RunnableLambda(wrapped_routing)


def process_routing_output(state: MessagesState) -> MessagesState:
    """
    Process routing agent output - mainly for validation and logging.

    URL messages are now created in StateToOutputTransformerNode as proper AIMessage+ToolMessage pairs.
    This function validates the state and logs for debugging.
    """
    try:
        logger.debug(f"[SUPERVISOR] State keys in process_routing_output: {list(state.keys())}")

        # Check if routing_output exists in state
        if "navigation_output" in state:
            navigation_output = state.get("navigation_output")
            logger.debug(f"[SUPERVISOR] Found navigation_output: {navigation_output}")

            if navigation_output and isinstance(navigation_output, dict):
                url = navigation_output.get("url")
                if url:
                    # URL already added to messages by StateToOutputTransformerNode
                    logger.info(f"[SUPERVISOR] Routing URL found: {url}")

                    # Verify URL is in messages
                    messages = state.get("messages", [])
                    has_url_message = any(
                        hasattr(msg, 'content') and url in str(msg.content)
                        for msg in messages
                    )
                    if has_url_message:
                        logger.debug("[SUPERVISOR] URL confirmed in messages")
                    else:
                        logger.warning("[SUPERVISOR] URL not found in messages, but already created by routing graph")
                else:
                    logger.debug("[SUPERVISOR] navigation_output exists but no URL found")
            else:
                logger.debug(f"[SUPERVISOR] navigation_output is not a dict or is empty: {navigation_output}")
        else:
            logger.debug("[SUPERVISOR] No navigation_output in state")

    except Exception as e:
        logger.warning(f"[SUPERVISOR] Error in process_routing_output: {e}", exc_info=True)

    return state


@register_graph("supervisor")
class SupervisorGraph(BaseGraph):
    """
    Supervisor graph that routes requests to routing and chat agents.
    Uses multi-destination pattern with handoff tools.
    """

    def __init__(
        self,
        llm: LLM,
        config: Optional[GraphConfig] = None
    ):
        """
        Initialize SupervisorGraph.

        Args:
            llm: Language model instance
            config: GraphConfig instance (optional)
        """
        if config is None:
            try:
                config = GraphConfig.from_yaml("src/graphs/supervisor/config.yaml")
            except FileNotFoundError:
                config = GraphConfig(name="supervisor")

        super().__init__(
            llm=llm,
            state_class=MessagesState,
            config=config,
            metadata=self._get_default_metadata(),
        )

    def _get_default_metadata(self) -> GraphMetadata:
        """Return default metadata for supervisor graph."""
        return GraphMetadata(
            name="supervisor",
            category="orchestration",
            capabilities=[
                GraphCapability.TEXT_UNDERSTANDING,
                GraphCapability.TOOL_USE,
            ],
            input_spec=InputSpec(
                name="messages",
                type="list[AnyMessage]",
                description="User messages for supervisor to route",
            ),
            output_spec=OutputSpec(
                name="messages",
                type="list[AnyMessage]",
                description="Response messages from supervisor or agents",
            ),
            version="1.0.0",
            tags=[
                "supervisor",
                "orchestration",
                "multi-agent",
                "handoff",
                "langgraph-compatible",
            ],
        )

    def build_graph(self) -> StateGraph:
        """
        Build and return the compiled supervisor graph.

        Graph Structure:
            START → supervisor → {routing, chat} → supervisor → END

        Returns:
            Compiled StateGraph instance
        """
        logger.info("[SUPERVISOR] Creating supervisor graph...")

        # Create supervisor agent with handoff tools
        logger.info("[SUPERVISOR] Creating ReAct agent with handoff tools:")
        logger.info("[SUPERVISOR]   - assign_to_chat_agent")
        logger.info("[SUPERVISOR]   - assign_to_routing_agent")
        logger.info("[SUPERVISOR]   - get_current_time")
        logger.info("[SUPERVISOR]   - get_supervisor_status")

        supervisor_agent = create_agent(
            model=self.llm.get_chat(),
            tools=[
                get_current_time,
                get_supervisor_status,
                assign_to_chat_agent,
                assign_to_routing_agent
            ],
            system_prompt=SUPERVISOR_SYSTEM_PROMPT,
            name="supervisor"
        )

        logger.info("[SUPERVISOR] Building routing agent...")
        # routing_agent = RoutingGraph(llm=self.llm).build_graph()
        routing_agent = VegaforzaNavigationGraph(llm=self.llm).build_graph()
        logger.info("[SUPERVISOR] Routing agent built successfully")

        logger.info("[SUPERVISOR] Building chat agent...")
        chat_agent = ChatGraph(llm=self.llm).build_graph()
        logger.info("[SUPERVISOR] Chat agent built successfully")

        # Build the graph with multi-destination pattern
        logger.info("[SUPERVISOR] Building supervisor graph structure...")
        builder = self.get_graph_builder()

        # Add nodes
        logger.info("[SUPERVISOR] Adding nodes:")
        logger.info("[SUPERVISOR]   - supervisor (with destinations: routing, chat)")
        logger.info("[SUPERVISOR]   - routing")
        logger.info("[SUPERVISOR]   - process_routing_output")
        logger.info("[SUPERVISOR]   - chat")

        builder.add_node("supervisor", supervisor_agent, destinations=["routing", "chat"])
        builder.add_node("routing", handle_routing_node(routing_agent))
        builder.add_node("process_routing_output", process_routing_output)
        builder.add_node("chat", chat_agent)

        # Define edges
        logger.info("[SUPERVISOR] Defining edges:")
        logger.info("[SUPERVISOR]   START → supervisor")
        logger.info("[SUPERVISOR]   supervisor → {routing, chat}")
        logger.info("[SUPERVISOR]   routing → process_routing_output")
        logger.info("[SUPERVISOR]   process_routing_output → supervisor")
        logger.info("[SUPERVISOR]   chat → supervisor")
        logger.info("[SUPERVISOR]   supervisor → END")

        builder.add_edge(START, "supervisor")
        builder.add_edge("routing", "process_routing_output")
        builder.add_edge("process_routing_output", "supervisor")
        builder.add_edge("chat", "supervisor")
        builder.add_edge("supervisor", END)

        # Compile with memory
        logger.info("[SUPERVISOR] Compiling supervisor graph...")
        compiled_graph = builder.compile(
            checkpointer=self.get_memory(),
            name="supervisor_graph"
        )
        logger.info("[SUPERVISOR] Supervisor graph compiled successfully ✓")

        return compiled_graph


def create_supervisor_graph(llm):
    """
    Legacy function for backward compatibility.

    Args:
        llm: Language model instance

    Returns:
        Compiled supervisor graph
    """
    return SupervisorGraph(llm=llm).build_graph()

