"""
Generic Text2SQL Graph Implementation.

Simple graph for parsing user queries into structured SQL intents.
"""

import logging
from typing import Optional
from langgraph.graph import StateGraph, START, END

logger = logging.getLogger(__name__)

from src.graphs.generic_text2sql.nodekit import GenericText2SQLNodeKit
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
# from .nodes import (
#     intent_parser_node,
#     intent_matching_node,
#     metadata_enrichment_node,
#     value_resolver_node,
#     sql_query_builder_node,
#     sql_executor_node,
#     # Optimized nodes
#     sql_architect_node,
#     sql_executor_node_with_retry,
#     # Business rules vector store node
#     retrieve_business_rules_node,
#     # Master table management nodes
#     create_master_table_node,
#     cleanup_master_table_node
# )


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

    def build_graph(self, use_optimized: bool = True) -> StateGraph:
        """
        Build and return the compiled StateGraph.

        Architecture (Optimized with Business Rules + Master Table):
        START → create_master_table → sql_architect → retrieve_business_rules → metadata_enrichment → value_resolver → sql_query_builder → sql_executor_with_retry → cleanup_master_table → END

        Architecture (Original):
        START → intent_parser → intent_matching → metadata_enrichment → value_resolver → sql_query_builder → sql_executor → END

        Args:
            use_optimized: If True, use collapsed architecture with master table (default). If False, use original.

        Returns:
            Compiled StateGraph instance
        """
        builder = self.get_graph_builder()

        if use_optimized:
            # OPTIMIZED ARCHITECTURE (Collapsed + Business Rules + Master Table)
            # Eliminates 1 LLM call by combining intent_parser + intent_matching
            # Adds business rules vector store retrieval
            # Manages MasterReportDocumentTable creation and cleanup
            logger.info("Building OPTIMIZED graph (collapsed architecture + business rules + master table)")

            nodekit = GenericText2SQLNodeKit(self.llm, self.config)

            # Add nodes
            builder.add_node("create_master_table", nodekit.create_master_table_node)
            builder.add_node("sql_architect", nodekit.sql_architect_node)
            builder.add_node("retrieve_business_rules", nodekit.retrieve_business_rules_node)
            builder.add_node("metadata_enrichment", nodekit.metadata_enrichment_node)
            builder.add_node("value_resolver", nodekit.value_resolver_node)
            builder.add_node("sql_query_builder", nodekit.sql_query_builder_node)
            builder.add_node("sql_executor", nodekit.sql_executor_node_with_retry)
            builder.add_node("cleanup_master_table", nodekit.cleanup_master_table_node)

            # Add edges (Sequential)
            builder.add_edge(START, "create_master_table")
            builder.add_edge("create_master_table", "sql_architect")
            builder.add_edge("sql_architect", "retrieve_business_rules")
            builder.add_edge("retrieve_business_rules", "metadata_enrichment")
            builder.add_edge("metadata_enrichment", "value_resolver")
            builder.add_edge("value_resolver", "sql_query_builder")
            builder.add_edge("sql_query_builder", "sql_executor")
            builder.add_edge("sql_executor", "cleanup_master_table")
            builder.add_edge("cleanup_master_table", END)

        else:
            # ORIGINAL ARCHITECTURE
            logger.info("Building ORIGINAL graph (legacy architecture)")

            # Add nodes
            builder.add_node("intent_parser", nodekit.intent_parser_node)
            builder.add_node("intent_matching", nodekit.intent_matching_node)
            builder.add_node("metadata_enrichment", nodekit.metadata_enrichment_node)
            builder.add_node("value_resolver", nodekit.value_resolver_node)
            builder.add_node("sql_query_builder", nodekit.sql_query_builder_node)
            builder.add_node("sql_executor", nodekit.sql_executor_node)

            # Add edges
            builder.add_edge(START, "intent_parser")
            builder.add_edge("intent_parser", "intent_matching")
            builder.add_edge("intent_matching", "metadata_enrichment")
            builder.add_edge("metadata_enrichment", "value_resolver")
            builder.add_edge("value_resolver", "sql_query_builder")
            builder.add_edge("sql_query_builder", "sql_executor")
            builder.add_edge("sql_executor", END)

        # Compile
        compiled = builder.compile(
            name="generic_text2sql_graph",
            checkpointer=self.get_memory(),
        )

        return compiled
