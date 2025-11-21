"""
Supervisor Graph - Multi-agent supervisor with routing and chat agents.
Routes requests between agents using handoff pattern.
"""
import logging
from typing import Optional
from langgraph.graph import StateGraph, START, END
from langgraph.graph import MessagesState
from langchain.agents import create_agent

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
from src.graphs.supervisor.prompts import SUPERVISOR_SYSTEM_PROMPT
from src.graphs.supervisor.tools import (
    get_current_time,
    get_supervisor_status,
    assign_to_chat_agent,
    assign_to_routing_agent
)

logger = logging.getLogger(__name__)


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
        routing_agent = RoutingGraph(llm=self.llm).build_graph()
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
        logger.info("[SUPERVISOR]   - chat")

        builder.add_node("supervisor", supervisor_agent, destinations=["routing", "chat"])
        builder.add_node("routing", routing_agent)
        builder.add_node("chat", chat_agent)

        # Define edges
        logger.info("[SUPERVISOR] Defining edges:")
        logger.info("[SUPERVISOR]   START → supervisor")
        logger.info("[SUPERVISOR]   supervisor → {routing, chat}")
        logger.info("[SUPERVISOR]   routing → supervisor")
        logger.info("[SUPERVISOR]   chat → supervisor")
        logger.info("[SUPERVISOR]   supervisor → END")

        builder.add_edge(START, "supervisor")
        builder.add_edge("routing", "supervisor")
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

