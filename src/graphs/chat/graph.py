"""
Chat Graph Implementation.

Defines ChatGraph class extending BaseGraph for chat interactions.
"""

from typing import Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

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
from .nodes import ChatNodes


@register_graph("chat")
class ChatGraph(BaseGraph):
    """
    Chat graph for conversational interactions.

    Extends BaseGraph with:
    - Configuration management (chat/config.yaml)
    - Metadata tracking
    - Type-safe state (ChatState)
    - Input/output validation
    - DI compatibility
    """

    def __init__(self, llm: LLM, config: Optional[GraphConfig] = None):
        """
        Initialize ChatGraph.

        Args:
            llm: Language model instance
            config: GraphConfig instance (optional, loads from config.yaml if None)
        """
        if config is None:
            config = GraphConfig.from_yaml("src/graphs/chat/config.yaml")

        super().__init__(
            llm=llm,
            state_class=ChatState,
            config=config,
            metadata=self._get_default_metadata(),
        )

    def _get_default_metadata(self) -> GraphMetadata:
        """
        Return default metadata for chat graph.

        Returns:
            GraphMetadata instance describing the chat graph
        """
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
            tags=["chat", "conversational", "llm-powered"],
        )

    def build_graph(self) -> StateGraph:
        """
        Build and return the compiled StateGraph for chat.

        Returns:
            Compiled StateGraph instance
        """
        # Create nodes handler
        nodes = ChatNodes(llm=self.llm)

        # Create graph builder
        builder = self.get_graph_builder()

        # Add nodes
        builder.add_node("process_message", nodes.process_message)

        # Add edges
        builder.add_edge(START, "process_message")
        builder.add_edge("process_message", END)

        # Compile and return with memory checkpointer
        return builder.compile(
            name="chat_graph",
            checkpointer=self.get_memory()
        )
