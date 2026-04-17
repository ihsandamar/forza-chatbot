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
from src.graphs.base.graph_metadata import (
    GraphMetadata,
    GraphCapability,
    InputSpec,
    OutputSpec,
)
from src.graphs.registry import register_graph, GRAPH_REGISTRY
from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration
from src.graphs.supervisor.prompts import SUPERVISOR_SYSTEM_PROMPT, SUPERVISOR_PROMPT_TEMPLATE
from src.graphs.supervisor.tools import get_current_time, get_supervisor_status
from src.graphs.supervisor.utilities import create_handoff_tool, create_forward_tool

logger = logging.getLogger(__name__)


@register_graph(
    name="supervisor",
    description="Orkestratör — kullanıcı mesajlarını doğru agent'a yönlendirir.",
    state_type="messages",
    returns_to_supervisor=False,
)
class SupervisorGraph(BaseGraph[SupervisorAssistantConfiguration]):
    """
    Supervisor graph that routes requests to routing and chat agents.
    Uses multi-destination pattern with handoff tools.
    """

    @classmethod
    def create(cls, llm: LLM, app_config=None) -> "SupervisorGraph":
        return cls(llm=llm, app_config=app_config)

    def __init__(
        self,
        llm: LLM,
        config: Optional[SupervisorAssistantConfiguration] = None,
        app_config=None,
    ):
        super().__init__(
            llm=llm,
            state_class=MessagesState,
            config=config,
            metadata=self._get_default_metadata(),
        )
        self.app_config = app_config

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

    def _resolve_agent_llm(self, agent_name: str) -> LLM:
        """Resolve which LLM to use for a given agent.

        Priority order:
        1. Studio override: app_config.<agent_name>_model (non-empty string)
        2. YAML agents section: app_config.agents.<agent_name>.model
        3. Global LLM (self.llm) — fallback

        Args:
            agent_name: Registry name of the agent (e.g. "routing", "report_agent").

        Returns:
            LLM instance — may be self.llm or a new instance with overridden model.
        """
        if self.app_config is None:
            return self.llm

        # 1. Studio override field (e.g. routing_model, chat_model, report_model)
        studio_field = f"{agent_name}_model"
        model_string = getattr(self.app_config, studio_field, None)
        if model_string:  # non-empty string — never pass "" to from_override
            try:
                return LLM.from_override(self.llm, model_string)
            except ValueError:
                logger.warning(
                    "[SUPERVISOR] Invalid model_string %r for agent %r (Studio field %r) — using global LLM",
                    model_string, agent_name, studio_field,
                )

        # 2. YAML agents.* section
        agents_cfg = getattr(self.app_config, "agents", None)
        if agents_cfg is not None:
            agent_cfg = getattr(agents_cfg, agent_name, None)
            if agent_cfg is not None:
                model = getattr(agent_cfg, "model", None)
                if model:
                    try:
                        return LLM.from_override(self.llm, model)
                    except ValueError:
                        logger.warning(
                            "[SUPERVISOR] Invalid model_string %r for agent %r (YAML agents.%s) — using global LLM",
                            model, agent_name, agent_name,
                        )

        # 3. Fall back to global LLM
        return self.llm

    def build_graph(self) -> StateGraph:
        """
        Build and return the compiled supervisor graph.
        Reads GRAPH_REGISTRY to discover agents and generates handoff tools dynamically.
        """
        logger.info("[SUPERVISOR] Registry'den agent'lar okunuyor...")

        # All registered agents except supervisor itself
        agents = {
            name: desc for name, desc in GRAPH_REGISTRY.items()
            if name != "supervisor"
        }

        # Generate handoff/forward tools dynamically
        handoff_tools = []
        for name, desc in agents.items():
            tool_description = desc.description
            if desc.examples:
                tool_description += "\n\nÖrnekler:\n" + "\n".join(f"- {ex}" for ex in desc.examples)

            if desc.returns_to_supervisor:
                tool_fn = create_handoff_tool(
                    agent_name=name,
                    description=tool_description,
                )
            else:
                tool_fn = create_forward_tool(
                    agent_name=name,
                    description=tool_description,
                )
            handoff_tools.append(tool_fn)

        all_tools = [get_current_time, get_supervisor_status] + handoff_tools

        # Build dynamic system prompt
        agent_descriptions = "\n".join(
            f"- {name}: {desc.description}" for name, desc in agents.items()
        )
        system_prompt = SUPERVISOR_PROMPT_TEMPLATE.format(
            agent_descriptions=agent_descriptions
        )

        supervisor_agent = create_agent(
            model=self.llm.get_chat(),
            tools=all_tools,
            system_prompt=system_prompt,
            name="supervisor"
        )

        builder = self.get_graph_builder()
        destinations = list(agents.keys())
        builder.add_node("supervisor", supervisor_agent, destinations=destinations)

        for name, desc in agents.items():
            try:
                agent_llm = self._resolve_agent_llm(name)
                subgraph = desc.cls.create(llm=agent_llm, app_config=self.app_config).build_graph()
                builder.add_node(name, subgraph)
                if desc.returns_to_supervisor:
                    builder.add_edge(name, "supervisor")
                else:
                    builder.add_edge(name, END)
                logger.info(f"[SUPERVISOR] ✓ {name} subgraph eklendi")
            except Exception as e:
                logger.error(f"[SUPERVISOR] {name} subgraph inşa hatası: {e}")

        builder.add_edge(START, "supervisor")
        builder.add_edge("supervisor", END)

        compiled = builder.compile(
            checkpointer=self.get_memory(),
            name="supervisor_graph"
        )
        logger.info("[SUPERVISOR] Supervisor graph derlendi ✓")
        return compiled
