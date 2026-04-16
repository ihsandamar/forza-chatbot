"""
Supervisor Graph - Multi-agent supervisor with routing and chat agents.
Routes requests between agents using handoff pattern.
"""
import logging
from pathlib import Path
from typing import Optional

from langgraph.graph import StateGraph, START, END
from langgraph.graph import MessagesState
from langchain.agents import create_agent
from langchain_core.messages import ToolMessage

from src.models.llm import LLM
from src.graphs.base.base_graph import BaseGraph
from src.graphs.base.graph_metadata import (
    GraphMetadata,
    GraphCapability,
    InputSpec,
    OutputSpec,
)
from src.graphs.registry import register_graph
from src.graphs.chat.graph import ChatGraph
from src.graphs.routing.graph import RoutingGraph
from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration

from src.graphs.supervisor.prompts import SUPERVISOR_SYSTEM_PROMPT
from src.graphs.supervisor.tools import (
    get_current_time,
    get_supervisor_status,
    assign_to_chat_agent,
    assign_to_routing_agent,
    assign_to_report_agent
)

logger = logging.getLogger(__name__)


def process_routing_output(state: MessagesState) -> MessagesState:
    """
    Process routing agent output - mainly for validation and logging.

    URL messages are now created in StateToOutputTransformerNode as proper AIMessage+ToolMessage pairs.
    This function validates the state and logs for debugging.
    """
    try:
        logger.debug(f"[SUPERVISOR] State keys in process_routing_output: {list(state.keys())}")

        if "navigation_output" in state:
            navigation_output = state.get("navigation_output")
            if navigation_output and isinstance(navigation_output, dict):
                url = navigation_output.get("url")
                if url:
                    logger.info(f"[SUPERVISOR] Routing URL found: {url}")
                    messages = state.get("messages", [])
                    has_url_message = any(
                        hasattr(msg, 'content') and url in str(msg.content)
                        for msg in messages
                    )
                    if has_url_message:
                        logger.debug("[SUPERVISOR] URL confirmed in messages")
                    else:
                        logger.warning("[SUPERVISOR] URL not found in messages, but already created by routing graph")

    except Exception as e:
        logger.warning(f"[SUPERVISOR] Error in process_routing_output: {e}", exc_info=True)

    return state


@register_graph("supervisor")
class SupervisorGraph(BaseGraph[SupervisorAssistantConfiguration]):
    """
    Supervisor graph that routes requests to routing and chat agents.
    Uses multi-destination pattern with handoff tools.
    """

    def __init__(
        self,
        llm: LLM,
        config: Optional[SupervisorAssistantConfiguration] = None
    ):
        super().__init__(
            llm=llm,
            state_class=MessagesState,
            config=config,
            metadata=self._get_default_metadata(),
        )

    def _get_default_config(self) -> SupervisorAssistantConfiguration:
        """Get default configuration for supervisor graph."""
        return SupervisorAssistantConfiguration(
            system_prompt=SUPERVISOR_SYSTEM_PROMPT,
            assistant_name="SupervisorAssistant",
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
            START → supervisor → {routing, chat, report}
              routing → process_routing_output → supervisor
              chat → supervisor
              report → END (passthrough)
            supervisor → END
        """
        logger.info("[SUPERVISOR] Creating supervisor graph...")

        # Create supervisor agent with handoff tools
        supervisor_agent = create_agent(
            model=self.llm.get_chat(),
            tools=[
                get_current_time,
                get_supervisor_status,
                assign_to_chat_agent,
                assign_to_routing_agent,
                assign_to_report_agent
            ],
            system_prompt=SUPERVISOR_SYSTEM_PROMPT,
            name="supervisor"
        )

        # Build subagents
        routing_config = self.config.get_routing_config()
        routing_agent = RoutingGraph(llm=self.llm, config=routing_config).build_graph()
        logger.info("[SUPERVISOR] ✓ Routing subgraph built")

        chat_config = self.config.get_chat_config()
        chat_agent = ChatGraph(llm=self.llm, config=chat_config).build_graph()
        logger.info("[SUPERVISOR] ✓ Chat subgraph built")

        # Build report agent as direct subgraph (native interrupt propagation)
        report_agent = None
        try:
            report_agent = self._build_report_agent()
            logger.info("[SUPERVISOR] ✓ Report subgraph built (own checkpointer for context preservation)")
        except Exception as e:
            logger.error(f"[SUPERVISOR] Failed to build report agent: {e}")
            logger.warning("[SUPERVISOR] Report agent disabled due to build error")

        # Build graph
        builder = self.get_graph_builder()

        destinations = ["routing", "chat"]
        if report_agent:
            destinations.append("report")

        builder.add_node("supervisor", supervisor_agent, destinations=destinations)
        builder.add_node("routing", routing_agent)
        builder.add_node("process_routing_output", process_routing_output)
        builder.add_node("chat", chat_agent)
        if report_agent:
            builder.add_node("report", report_agent)

        # Edges
        builder.add_edge(START, "supervisor")
        builder.add_edge("routing", "process_routing_output")
        builder.add_edge("process_routing_output", "supervisor")
        builder.add_edge("chat", "supervisor")
        if report_agent:
            builder.add_edge("report", END)
        builder.add_edge("supervisor", END)

        # Compile
        compiled_graph = builder.compile(
            checkpointer=self.get_memory(),
            name="supervisor_graph"
        )
        logger.info("[SUPERVISOR] Supervisor graph compiled successfully ✓")

        return compiled_graph

    def _build_report_agent(self):
        """Build report agent subgraph with its own checkpointer for context preservation.

        The report agent gets checkpointer=True so it inherits the parent
        supervisor's checkpointer. This means ReportState fields (active_sql,
        active_results, active_filters) persist between turns. Without this,
        the supervisor only sees MessagesState and all other fields are lost.

        Interrupt propagation is unaffected — GraphInterrupt bubbles up via
        exception chain regardless of checkpointer configuration.
        """
        from src.graphs.report_agent.graph import build_report_agent_graph
        from src.services.config_loader import ConfigLoader

        config = ConfigLoader.load_config()
        project_root = Path(__file__).parent.parent.parent.parent
        business_rules_path = str(project_root / "src" / "graphs" / "report_agent" / "data" / "business_rules.json")
        chroma_persist_dir = str(project_root / "data" / "vector_store")

        return build_report_agent_graph(
            llm=self.llm.get_chat(),
            table_name=self.config.report_table_name,
            column_metadata=self.config.report_column_metadata,
            connection_string=config.database.uri,
            business_rules_path=business_rules_path,
            chroma_persist_dir=chroma_persist_dir,
            checkpointer=True,
        )


def create_supervisor_graph(llm):
    """Legacy function for backward compatibility."""
    return SupervisorGraph(llm=llm).build_graph()
