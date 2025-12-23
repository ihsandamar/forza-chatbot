"""
Generic Text2SQL Graph Implementation.

Simple graph for parsing user queries into structured SQL intents.
"""

from typing import Optional
from langgraph.graph import StateGraph, START, END

from src.models.llm import LLM
from src.graphs.base.base_graph import BaseGraph
from src.graphs.base.graph_metadata import (
    GraphMetadata,
    GraphCapability,
    InputSpec,
    OutputSpec,
)
from src.graphs.registry import register_graph
from src.graphs.generic_text2sql.assistant_configuration import GenericSQLAssistantConfiguration
from .state import GenericText2SQLState
from .nodes import (
    intent_parser_node,
    intent_matching_node,
    value_resolver_node,
    sql_query_builder_node,
    sql_executor_node
)


@register_graph("generic_text2sql")
class GenericText2SQLGraph(BaseGraph[GenericSQLAssistantConfiguration]):
    """
    Generic Text2SQL graph for parsing user queries into SQL.

    Simple single-node architecture with intent parser.
    """

    def __init__(
        self,
        llm: LLM,
        config: Optional[GenericSQLAssistantConfiguration] = None
    ):
        """
        Initialize GenericText2SQLGraph.

        Args:
            llm: Language model instance
            config: GenericSQLAssistantConfiguration instance (optional)
        """
        super().__init__(
            llm=llm,
            state_class=GenericText2SQLState,
            config=config,
            metadata=self._get_default_metadata(),
        )

    def _get_default_config(self) -> GenericSQLAssistantConfiguration:
        """
        Get default configuration for generic text2sql graph.

        Returns:
            GenericSQLAssistantConfiguration with default values
        """
        return GenericSQLAssistantConfiguration(
            system_prompt="Sen bir ERP uzmanı ve SQL sorgulama asistanısın.",
            assistant_name="GenericSQL Assistant"
        )

    def _get_default_metadata(self) -> GraphMetadata:
        """Return default metadata for generic text2sql graph."""
        return GraphMetadata(
            name="generic_text2sql",
            category="text2sql",
            capabilities=[
                GraphCapability.TEXT_UNDERSTANDING
            ],
            input_spec=InputSpec(
                name="user_query",
                type="str",
                description="User's natural language query",
            ),
            output_spec=OutputSpec(
                name="parsed_intent",
                type="dict",
                description="Structured SQL intent with steps and filters",
            ),
            version="1.0.0",
            tags=[
                "text2sql",
                "intent-parsing",
                "sql",
                "turkish",
                "erp",
            ],
        )

    def build_graph(self) -> StateGraph:
        """
        Build and return the compiled StateGraph.

        Architecture:
        START → intent_parser → intent_matching → value_resolver → sql_query_builder → sql_executor → END

        Returns:
            Compiled StateGraph instance
        """
        builder = self.get_graph_builder()

        # Add nodes
        builder.add_node("intent_parser", intent_parser_node)
        builder.add_node("intent_matching", intent_matching_node)
        builder.add_node("value_resolver", value_resolver_node)
        builder.add_node("sql_query_builder", sql_query_builder_node)
        builder.add_node("sql_executor", sql_executor_node)

        # Add edges
        builder.add_edge(START, "intent_parser")
        builder.add_edge("intent_parser", "intent_matching")
        builder.add_edge("intent_matching", "value_resolver")
        builder.add_edge("value_resolver", "sql_query_builder")
        builder.add_edge("sql_query_builder", "sql_executor")
        builder.add_edge("sql_executor", END)

        # Compile
        compiled = builder.compile(
            name="generic_text2sql_graph",
            checkpointer=self.get_memory(),
        )

        return compiled
