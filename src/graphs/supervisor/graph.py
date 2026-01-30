"""
Supervisor Graph - Multi-agent supervisor with routing and chat agents.
Routes requests between agents using handoff pattern.
"""
import logging
import numpy
from typing import Optional
from langgraph.graph import StateGraph, START, END
from langgraph.graph import MessagesState
from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda

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
from langchain_core.runnables import RunnableLambda

logger = logging.getLogger(__name__)


async def create_subagents(llm: LLM, runtime: dict):
    """
    Create all subagents using runtime configuration.

    This pattern avoids initializing graphs with config in constructor,
    instead getting config from runtime configurable parameters.

    Args:
        llm: Language model instance
        runtime: Runtime dict with configurable parameters

    Returns:
        Tuple of (routing_agent, chat_agent) compiled graphs
    """
    from src.graphs.routing.assistant_configuration import RoutingAssistantConfiguration
    from src.graphs.chat.assistant_configuration import ChatAssistantConfiguration
    from src.services.config_loader import ConfigLoader

    # Get configurable parameters from runtime
    configurable = runtime.get("configurable", {})

    # Get routing config from runtime
    routing_token = configurable.get("routing_token", "")
    routing_system_prompt = configurable.get(
        "routing_system_prompt",
        "Sen Forza navigasyon asistanısın. Kullanıcıları doğru sayfalara yönlendirirsin."
    )
    routing_model = configurable.get("routing_model", "anthropic:claude-haiku-4-5")

    # Get chat config from runtime
    chat_system_prompt = configurable.get(
        "chat_system_prompt",
        "Sen yardımcı bir sohbet asistanısın. Kullanıcılarla doğal ve samimi bir şekilde konuşursun."
    )
    chat_model = configurable.get("chat_model", "anthropic:claude-haiku-4-5")

    logger.info("[SUPERVISOR] Creating subagents with runtime config...")
    logger.debug(f"[SUPERVISOR] Routing token from runtime: {'***' if routing_token else 'EMPTY'}")

    # Create routing agent with runtime config
    routing_config = RoutingAssistantConfiguration(
        token=routing_token,
        system_prompt=routing_system_prompt,
        assistant_name="RoutingAssistant"
    )
    routing_agent = RoutingGraph(llm=llm, config=routing_config).build_graph()
    logger.info("[SUPERVISOR] ✓ Routing subgraph built with runtime config")

    # Create chat agent with runtime config
    chat_config = ChatAssistantConfiguration(
        system_prompt=chat_system_prompt,
        assistant_name="ChatAssistant"
    )
    chat_agent = ChatGraph(llm=llm, config=chat_config).build_graph()
    logger.info("[SUPERVISOR] ✓ Chat subgraph built with runtime config")

    return routing_agent, chat_agent


def prepare_routing_config_node(default_supervisor_config):
    """
    Prepare routing configuration from supervisor config.

    This node extracts routing config from supervisor config and injects it into state.
    This allows routing subgraph to access runtime config via state.

    Args:
        default_supervisor_config: Default SupervisorAssistantConfiguration (fallback)
    """
    async def prepare_config(state: MessagesState, config: dict = None) -> MessagesState:
        logger.info("[SUPERVISOR] Preparing routing config...")

        try:
            # Get supervisor config (runtime from LangGraph or default)
            supervisor_config = default_supervisor_config

            # Try to get runtime config from LangGraph config parameter
            if config and 'configurable' in config:
                runtime_configurable = config['configurable']

                if hasattr(runtime_configurable, 'get_routing_config'):
                    supervisor_config = runtime_configurable
                    logger.info("[SUPERVISOR] Using runtime supervisor config from LangGraph Studio")

            # Extract routing config
            routing_config = supervisor_config.get_routing_config()
            logger.debug(f"[SUPERVISOR] Routing token: {'***' if routing_config.token else 'EMPTY'}")

            # Inject routing config fields into state for routing subgraph
            state["token"] = routing_config.token
            state["routing_system_prompt"] = routing_config.system_prompt
            logger.info("[SUPERVISOR] Routing config injected into state")

            return state

        except Exception as e:
            logger.error(f"[SUPERVISOR] Error preparing routing config: {e}", exc_info=True)
            raise

    return RunnableLambda(prepare_config)


def handle_routing_node_OLD_UNUSED(routing_graph_instance, default_supervisor_config):
    """
    Wrapper for routing agent that handles state conversion and runtime configuration.

    Runtime Configuration:
    - Gets supervisor config at runtime (from LangGraph config parameter)
    - Extracts routing config from supervisor config
    - Passes runtime config to routing agent via invoke
    - This ensures LangGraph Studio config changes are applied

    State Conversion:
    - Input: MessagesState (supervisor format with 'messages' list)
    - Output: RoutingState (routing format with 'message' singular)

    Args:
        routing_graph_instance: Pre-built RoutingGraph instance (for LangGraph Dev subgraph display)
        default_supervisor_config: Default SupervisorAssistantConfiguration (fallback)
    """
    async def wrapped_routing(state: MessagesState, config: dict = None) -> MessagesState:
        logger.info("[SUPERVISOR] Invoking routing agent...")

        try:
            # ============================================
            # Step 0: Get runtime config
            # ============================================
            # Get supervisor config (runtime from LangGraph or default)
            supervisor_config = default_supervisor_config

            # Try to get runtime config from LangGraph config parameter
            if config and 'configurable' in config:
                runtime_configurable = config['configurable']
                logger.debug(f"[SUPERVISOR] Runtime config type: {type(runtime_configurable)}")

                # If runtime config is SupervisorAssistantConfiguration, use it
                if hasattr(runtime_configurable, 'get_routing_config'):
                    supervisor_config = runtime_configurable
                    logger.info("[SUPERVISOR] Using runtime config from LangGraph Studio")
                else:
                    logger.warning("[SUPERVISOR] Runtime config is not SupervisorAssistantConfiguration, using default")
            else:
                logger.debug("[SUPERVISOR] No runtime config, using default")

            # Extract routing config from supervisor config
            routing_config = supervisor_config.get_routing_config()
            logger.debug(f"[SUPERVISOR] Routing token from config: {'***' if routing_config.token else 'EMPTY'}")

            # ============================================
            # Step 1: Convert MessagesState to RoutingState
            # ============================================
            messages = state.get("messages", [])
            logger.debug(f"[SUPERVISOR] Total messages in state: {len(messages)}")

            # Get the last user message
            user_message = None
            for msg in reversed(messages):
                # Find last HumanMessage (user input)
                if hasattr(msg, '__class__') and msg.__class__.__name__ == 'HumanMessage':
                    user_message = msg
                    logger.debug(f"[SUPERVISOR] Found user message: {str(msg.content)[:100]}...")
                    break

            # Create routing state with message field
            routing_state = {
                "message": user_message,
                "messages": messages,  # Also keep messages for context
            }

            logger.info("[SUPERVISOR] Converted state for routing agent")
            logger.debug(f"[SUPERVISOR] Routing state keys: {list(routing_state.keys())}")

            # ============================================
            # Step 2: Invoke routing agent with runtime config
            # ============================================
            # Build routing agent with runtime config (fresh instance for runtime config)
            from src.graphs.routing.graph import RoutingGraph
            routing_graph_runtime = RoutingGraph(llm=routing_graph_instance.llm, config=routing_config)
            routing_agent_compiled = routing_graph_runtime.build_graph()

            # Invoke with LangGraph native config (dict format)
            # BaseGraph._inject_config_to_state will handle the config injection
            routing_output = await routing_graph_runtime.ainvoke(routing_state, {"configurable": routing_config})
            logger.debug(f"[SUPERVISOR] Routing output type: {type(routing_output)}")
            logger.debug(f"[SUPERVISOR] Routing output keys: {list(routing_output.keys()) if hasattr(routing_output, 'keys') else 'N/A'}")

            # ============================================
            # Step 3: Convert RoutingState back to MessagesState
            # ============================================
            # Copy relevant fields from routing output back to supervisor state
            if isinstance(routing_output, dict):
                # Preserve routing-specific results
                if "most_relevant_page" in routing_output:
                    state["most_relevant_page"] = routing_output.get("most_relevant_page")
                    logger.debug("[SUPERVISOR] Preserved most_relevant_page from routing")

                if "page_parameters" in routing_output:
                    state["page_parameters"] = routing_output.get("page_parameters")
                    logger.debug("[SUPERVISOR] Preserved page_parameters from routing")

                if "retrieved_documents" in routing_output:
                    state["retrieved_documents"] = routing_output.get("retrieved_documents")
                    logger.debug("[SUPERVISOR] Preserved retrieved_documents from routing")

                # Update messages if routing agent added any
                if "messages" in routing_output:
                    state["messages"] = routing_output.get("messages")
                    logger.debug("[SUPERVISOR] Updated messages from routing output")

            logger.info("[SUPERVISOR] Routing agent completed successfully")
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


def handle_report_node(report_graph_compiled, supervisor_config):
    """
    Wrapper for report agent that handles runtime configuration injection.

    This node:
    1. Extracts report config from supervisor config
    2. Converts supervisor state to report state
    3. Invokes report graph with proper RunnableConfig
    4. Returns result back to supervisor state

    Args:
        report_graph_compiled: Compiled report graph instance
        supervisor_config: Default SupervisorAssistantConfiguration (fallback)

    Returns:
        RunnableLambda that wraps the report agent
    """
    async def wrapped_report(state: MessagesState, config: dict = None) -> MessagesState:
        logger.info("[SUPERVISOR] Invoking report agent with runtime config...")

        try:
            # ============================================
            # Step 1: Extract report config from runtime or default
            # ============================================
            report_config = None

            # Try runtime config first
            if config and 'configurable' in config:
                runtime_configurable = config['configurable']
                logger.debug(f"[SUPERVISOR] Runtime config type: {type(runtime_configurable)}")

                # If runtime config has get_report_config method
                if hasattr(runtime_configurable, 'get_report_config'):
                    report_config = runtime_configurable.get_report_config()
                    logger.info("[SUPERVISOR] Using report config from runtime (get_report_config)")
                # Or if it's a dict with report fields
                elif isinstance(runtime_configurable, dict):
                    # Check if dict has report fields
                    if 'report_table_name' in runtime_configurable or 'table_name' in runtime_configurable:
                        from src.graphs.generic_text2sql.assistant_configuration import GenericSQLAssistantConfiguration
                        report_config = GenericSQLAssistantConfiguration(
                            report_name=runtime_configurable.get('report_name', ''),
                            description=runtime_configurable.get('report_description', ''),
                            table_name=runtime_configurable.get('report_table_name') or runtime_configurable.get('table_name', 'MasterReportDocumentTable'),
                            query=runtime_configurable.get('report_query') or runtime_configurable.get('query', ''),
                            column_metadata=runtime_configurable.get('report_column_metadata') or runtime_configurable.get('column_metadata', {}),
                            business_rules=runtime_configurable.get('report_business_rules') or runtime_configurable.get('business_rules', []),
                            system_prompt=runtime_configurable.get('report_system_prompt', 'Sen bir ERP uzmanı ve SQL sorgulama asistanısın.'),
                            assistant_name="ReportAssistant"
                        )
                        logger.info("[SUPERVISOR] Using report config from runtime dict")

            # Fallback to default supervisor config
            if report_config is None:
                report_config = supervisor_config.get_report_config()
                logger.info("[SUPERVISOR] Using report config from default supervisor config")

            logger.info(f"[SUPERVISOR] Report config: table={report_config.table_name}, report={report_config.report_name or 'default'}")

            # ============================================
            # Step 2: Prepare report input state
            # ============================================
            messages = state.get("messages", [])
            logger.debug(f"[SUPERVISOR] Passing {len(messages)} messages to report agent")

            # Report graph expects messages
            report_input = {
                "messages": messages,
                "text2sql_output": None,
                "visualization_output": None,
                "error": None,
                "no_records_message": None,
                # New stateful fields
                "active_query_context": state.get("active_query_context"),
                "query_history": state.get("query_history", []),
                "pending_question": None,
                "waiting_for_user_input": False,
                "user_clarification": None
            }

            # ============================================
            # Step 3: Invoke report graph with report config
            # ============================================
            # Create RunnableConfig with report-specific configuration
            # LangGraph expects configurable to be a dict, not Pydantic model
            # Also need to pass thread_id from parent config for checkpointer
            report_config_dict = report_config.model_dump() if hasattr(report_config, 'model_dump') else dict(report_config)

            # Merge with parent config's thread_id and other required fields
            if config and 'configurable' in config:
                parent_configurable = config['configurable']
                if isinstance(parent_configurable, dict):
                    # Copy thread_id and checkpoint_ns from parent
                    if 'thread_id' in parent_configurable:
                        report_config_dict['thread_id'] = parent_configurable['thread_id']
                    if 'checkpoint_ns' in parent_configurable:
                        report_config_dict['checkpoint_ns'] = parent_configurable['checkpoint_ns']

            report_runtime_config = {
                "configurable": report_config_dict
            }

            logger.info("[SUPERVISOR] Invoking report graph...")
            report_output = await report_graph_compiled.ainvoke(report_input, report_runtime_config)

            logger.debug(f"[SUPERVISOR] Report output keys: {list(report_output.keys()) if hasattr(report_output, 'keys') else 'N/A'}")

            # ============================================
            # Step 4: Merge report output back to supervisor state
            # ============================================
            if isinstance(report_output, dict):
                # Update messages
                if "messages" in report_output:
                    state["messages"] = report_output["messages"]
                    logger.debug(f"[SUPERVISOR] Updated messages from report output")

                # Preserve stateful fields for next invocation
                if "active_query_context" in report_output:
                    state["active_query_context"] = report_output["active_query_context"]
                if "query_history" in report_output:
                    state["query_history"] = report_output["query_history"]

                # Preserve report outputs for potential further processing
                if "text2sql_output" in report_output:
                    state["text2sql_output"] = report_output["text2sql_output"]
                if "visualization_output" in report_output:
                    state["visualization_output"] = report_output["visualization_output"]

            logger.info("[SUPERVISOR] Report agent completed successfully")
            return state

        except Exception as e:
            logger.error(f"[SUPERVISOR] Error in report agent: {e}", exc_info=True)
            raise

    return RunnableLambda(wrapped_report)


@register_graph("supervisor")
class SupervisorGraph(BaseGraph[SupervisorAssistantConfiguration]):
    """
    Supervisor graph that routes requests to routing and chat agents.
    Uses multi-destination pattern with handoff tools.

    Architecture:
    - Uses composition pattern for sub-agent configurations
    - Each sub-agent (routing, chat) has its own configuration
    - Follows SOLID principles for maintainability
    """

    def __init__(
        self,
        llm: LLM,
        config: Optional[SupervisorAssistantConfiguration] = None
    ):
        """
        Initialize SupervisorGraph.

        Args:
            llm: Language model instance
            config: SupervisorAssistantConfiguration instance (optional)
        """
        super().__init__(
            llm=llm,
            state_class=MessagesState,
            config=config,
            metadata=self._get_default_metadata(),
        )

    def _get_default_config(self) -> SupervisorAssistantConfiguration:
        """
        Get default configuration for supervisor graph.

        Returns:
            SupervisorAssistantConfiguration with flat fields

        Note:
            routing_token is intentionally empty and should be set at runtime.
            Use LangGraph Studio UI or pass via configurable parameters.
        """
        logger.debug("[SUPERVISOR] Using empty routing token, will be set at runtime")

        # Create supervisor configuration with flat fields
        return SupervisorAssistantConfiguration(
            # Supervisor config
            system_prompt=SUPERVISOR_SYSTEM_PROMPT,
            assistant_name="SupervisorAssistant",

            # Routing sub-agent config (flat fields)
            routing_token="",  # Empty by design - set at runtime
            routing_system_prompt="Sen Forza navigasyon asistanısın. Kullanıcıları doğru sayfalara yönlendirirsin.",
            routing_model="anthropic:claude-haiku-4-5",

            # Chat sub-agent config (flat fields)
            chat_system_prompt="Sen yardımcı bir sohbet asistanısın. Kullanıcılarla doğal ve samimi bir şekilde konuşursun.",
            chat_model="anthropic:claude-haiku-4-5",

            # Report sub-agent config (flat fields)
            report_name="",  # Empty by design - set at runtime
            report_description="",
            report_table_name="MasterReportDocumentTable",
            report_query="",  # SQL query - set at runtime
            report_column_metadata={},
            report_business_rules=[],
            report_system_prompt="Sen bir ERP uzmanı ve SQL sorgulama asistanısın.",
            report_model="anthropic:claude-sonnet-4-5"
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
        logger.info("[SUPERVISOR]   - assign_to_report_agent")
        logger.info("[SUPERVISOR]   - get_current_time")
        logger.info("[SUPERVISOR]   - get_supervisor_status")

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

        logger.info("[SUPERVISOR] Building subagents with default config (runtime config will override)...")
        # Build subagents with default config from self.config
        # Runtime config will be injected via prepare_routing_config node
        routing_config = self.config.get_routing_config()
        routing_agent = RoutingGraph(llm=self.llm, config=routing_config).build_graph()
        logger.info("[SUPERVISOR] ✓ Routing subgraph built (runtime config via prepare_routing_config)")

        # Get chat configuration from supervisor config
        chat_config = self.config.get_chat_config()
        chat_agent = ChatGraph(llm=self.llm, config=chat_config).build_graph()
        logger.info("[SUPERVISOR] ✓ Chat subgraph built")

        # Build report agent (text2sql + visualization)
        # Use lazy import to avoid dependency issues during graph build
        logger.info("[SUPERVISOR] Building report agent...")

        def build_report_agent_lazy():
            """Lazy builder for report agent - only imports when needed"""
            from src.graphs.generic_text2sql.graph import GenericText2SQLGraph
            from src.graphs.data_visualization.graph import build_visualization_graph
            from src.graphs.report.graph import build_report_graph

            # Get report configuration from supervisor config (build-time default)
            report_config = self.config.get_report_config()
            logger.info(f"[SUPERVISOR] Report build-time config: table={report_config.table_name}, report={report_config.report_name or 'default'}")

            # Build text2sql graph with report config
            text2sql_graph = GenericText2SQLGraph(llm=self.llm, config=report_config).build_graph()
            logger.info("[SUPERVISOR] ✓ Text2SQL subgraph built with config")

            # Build visualization graph
            visualization_graph = build_visualization_graph(llm=self.llm)
            logger.info("[SUPERVISOR] ✓ Visualization subgraph built")

            # Build report graph (combines text2sql + visualization)
            # Use GenericSQLAssistantConfiguration as config schema for runtime config
            from src.graphs.generic_text2sql.assistant_configuration import GenericSQLAssistantConfiguration
            report_graph = build_report_graph(
                text2sql_graph=text2sql_graph,
                visualization_graph=visualization_graph,
                llm=self.llm,
                enable_hitl=True,
                config_schema=GenericSQLAssistantConfiguration
            )
            logger.info("[SUPERVISOR] ✓ Report subgraph built (HITL enabled, config_schema set)")
            return report_graph

        # Build report agent (this will import dependencies)
        report_agent = None
        report_agent_wrapper = None
        try:
            report_agent = build_report_agent_lazy()
            # Create wrapper node for runtime config injection
            report_agent_wrapper = handle_report_node(report_agent, self.config)
            logger.info("[SUPERVISOR] ✓ Report agent wrapper created (runtime config will be injected)")
        except Exception as e:
            logger.error(f"[SUPERVISOR] Failed to build report agent: {e}")
            logger.warning("[SUPERVISOR] Report agent disabled due to build error")

        # Build the graph with multi-destination pattern
        logger.info("[SUPERVISOR] Building supervisor graph structure...")
        builder = self.get_graph_builder()

        # Add nodes
        destinations = ["routing", "chat"]
        if report_agent_wrapper:
            destinations.append("report")

        logger.info("[SUPERVISOR] Adding nodes:")
        logger.info(f"[SUPERVISOR]   - supervisor (with destinations: {', '.join(destinations)})")
        logger.info("[SUPERVISOR]   - routing (SUBGRAPH - will be visible)")
        logger.info("[SUPERVISOR]   - process_routing_output")
        logger.info("[SUPERVISOR]   - chat (SUBGRAPH - visible)")
        if report_agent_wrapper:
            logger.info("[SUPERVISOR]   - report (WRAPPER with runtime config injection)")

        builder.add_node("supervisor", supervisor_agent, destinations=destinations)

        # Routing subgraph: Directly added (visible as subgraph in LangGraph Dev)
        builder.add_node("routing", routing_agent)

        builder.add_node("process_routing_output", process_routing_output)
        builder.add_node("chat", chat_agent)

        # Add report agent wrapper (handles runtime config injection)
        if report_agent_wrapper:
            builder.add_node("report", report_agent_wrapper)

        # Define edges
        edge_list = "{routing, chat" + (", report}" if report_agent_wrapper else "}")
        logger.info("[SUPERVISOR] Defining edges:")
        logger.info("[SUPERVISOR]   START → supervisor")
        logger.info(f"[SUPERVISOR]   supervisor → {edge_list}")
        logger.info("[SUPERVISOR]   routing → process_routing_output")
        logger.info("[SUPERVISOR]   process_routing_output → supervisor")
        logger.info("[SUPERVISOR]   chat → supervisor")
        if report_agent_wrapper:
            logger.info("[SUPERVISOR]   report → supervisor")
        logger.info("[SUPERVISOR]   supervisor → END")

        builder.add_edge(START, "supervisor")
        builder.add_edge("routing", "process_routing_output")
        builder.add_edge("process_routing_output", "supervisor")
        builder.add_edge("chat", "supervisor")

        # Add report edge only if agent wrapper exists
        if report_agent_wrapper:
            builder.add_edge("report", "supervisor")

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

