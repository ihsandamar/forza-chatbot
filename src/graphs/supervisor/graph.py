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
    assign_to_routing_agent
)

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
            chat_model="anthropic:claude-haiku-4-5"
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

        # Build the graph with multi-destination pattern
        logger.info("[SUPERVISOR] Building supervisor graph structure...")
        builder = self.get_graph_builder()

        # Add nodes
        logger.info("[SUPERVISOR] Adding nodes:")
        logger.info("[SUPERVISOR]   - supervisor (with destinations: routing, chat)")
        logger.info("[SUPERVISOR]   - routing (SUBGRAPH - will be visible)")
        logger.info("[SUPERVISOR]   - process_routing_output")
        logger.info("[SUPERVISOR]   - chat (SUBGRAPH - visible)")

        builder.add_node("supervisor", supervisor_agent, destinations=["routing", "chat"])

        # Routing subgraph: Directly added (visible as subgraph in LangGraph Dev)
        builder.add_node("routing", routing_agent)

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

