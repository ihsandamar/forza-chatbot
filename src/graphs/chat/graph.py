"""
Chat Graph Implementation.

Simple chat graph with tool-equipped agent.
"""

from typing import Optional
from langgraph.graph import StateGraph, START, END

from src.models.models import LLM
from src.graphs.base.base_graph import BaseGraph
from src.graphs.base.graph_config import GraphConfig
from src.graphs.base.graph_metadata import (
    GraphMetadata,
    GraphCapability,
    InputSpec,
    OutputSpec,
)
from src.graphs.registry import register_graph
from .state import ChatState
from .nodes import chat_node


@register_graph("chat")
class ChatGraph(BaseGraph):
    """
    Chat graph for conversational interactions.

    Simple single-node architecture with tool-equipped agent.
    """

    def __init__(
        self,
        llm: LLM,
        config: Optional[GraphConfig] = None
    ):
        """
        Initialize ChatGraph.

        Args:
            llm: Language model instance
            config: GraphConfig instance (optional)
        """
        if config is None:
            try:
                config = GraphConfig.from_yaml("src/graphs/chat/config.yaml")
            except FileNotFoundError:
                config = GraphConfig(name="chat")

        super().__init__(
            llm=llm,
            state_class=ChatState,
            config=config,
            metadata=self._get_default_metadata(),
        )

    def _get_default_metadata(self) -> GraphMetadata:
        """Return default metadata for chat graph."""
        return GraphMetadata(
            name="chat",
            category="chat",
            capabilities=[
                GraphCapability.TEXT_GENERATION,
                GraphCapability.TEXT_UNDERSTANDING,
            ],
            input_spec=InputSpec(
                name="messages",
                type="list[dict]",
                description="Conversation message history",
            ),
            output_spec=OutputSpec(
                name="messages",
                type="list[dict]",
                description="Updated conversation with assistant response",
            ),
            version="1.0.0",
            tags=[
                "chat",
                "conversational",
                "llm-powered",
                "turkish",
                "customer-service",
            ],
        )

    def build_graph(self) -> StateGraph:
        """
        Build and return the compiled StateGraph.

        Simple architecture:
        START → chat → END

        Returns:
            Compiled StateGraph instance
        """
        builder = self.get_graph_builder()

        # Add single chat node
        builder.add_node("chat", chat_node)

        # Add edges
        builder.add_edge(START, "chat")
        builder.add_edge("chat", END)

        # Compile
        compiled = builder.compile(
            name="chat_graph",
            checkpointer=self.get_memory(),
        )

        return compiled
