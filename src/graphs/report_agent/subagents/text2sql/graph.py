"""
Text2SQL Subagent Graph

START → sql_planner → value_resolver → business_rules → sql_builder → sql_executor
                                                                ↑              ↓
                                                         (retry, max 2) ←──────┘
                                                                               ↓
                                                                              END

Shared State: Text2SQLState (ReportState overlapping keys LangGraph'ın
              subgraph mekanizması ile parent'a otomatik taşınır)
"""
import logging
from pathlib import Path
from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.subagents.text2sql.business_rules_vector_store import BusinessRulesVectorStore
from src.graphs.report_agent.subagents.text2sql.nodes import (
    MAX_RETRY,
    create_business_rules_node,
    create_sql_builder_node,
    create_sql_executor_node,
    create_sql_planner_node,
    create_value_resolver_node,
)
from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
from src.graphs.report_agent.subagents.text2sql.value_resolver_service import ValueResolverService

logger = logging.getLogger(__name__)


def _route_after_executor(state: dict) -> str:
    """
    Retry routing: sql_error set ve retry < MAX_RETRY ise sql_builder'a dön.
    Aksi halde END.
    """
    if state.get("sql_error") and state.get("retry_count", 0) <= MAX_RETRY:
        logger.info(f"[TEXT2SQL] Retry {state['retry_count']}/{MAX_RETRY} → sql_builder")
        return "sql_builder"
    return END


def build_text2sql_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    connection_string: str,
    business_rules_path: str,
    chroma_persist_dir: str,
):
    """
    Text2SQL subgraph'ı inşa et.

    Args:
        llm: ChatOpenAI veya uyumlu LLM
        table_name: Hedef DB tablo adı
        column_metadata: {kolon_adı: {type, description, ...}}
        connection_string: pyodbc bağlantı string'i
        business_rules_path: business_rules.json dosya yolu
        chroma_persist_dir: ChromaDB persist klasörü

    Returns:
        Compiled StateGraph (Text2SQLState)
    """
    logger.info(f"[TEXT2SQL] Building subgraph for table: {table_name}")

    # --- Servis başlatma ---
    value_resolver = ValueResolverService(
        db_connection_string=connection_string,
        table_name=table_name,
    )

    vector_store = BusinessRulesVectorStore(
        rules_file_path=business_rules_path,
        persist_directory=chroma_persist_dir,
    )
    vector_store.initialize_collections()

    # --- Node factories ---
    sql_planner = create_sql_planner_node(llm, column_metadata)
    value_resolver_node = create_value_resolver_node(value_resolver)
    business_rules_node = create_business_rules_node(vector_store)
    sql_builder = create_sql_builder_node(llm, table_name, column_metadata)
    sql_executor = create_sql_executor_node(connection_string)

    # --- Graph ---
    graph = StateGraph(Text2SQLState)

    graph.add_node("sql_planner", sql_planner)
    graph.add_node("value_resolver", value_resolver_node)
    graph.add_node("business_rules", business_rules_node)
    graph.add_node("sql_builder", sql_builder)
    graph.add_node("sql_executor", sql_executor)

    graph.add_edge(START, "sql_planner")
    graph.add_edge("sql_planner", "value_resolver")
    graph.add_edge("value_resolver", "business_rules")
    graph.add_edge("business_rules", "sql_builder")
    graph.add_edge("sql_builder", "sql_executor")
    graph.add_conditional_edges(
        "sql_executor",
        _route_after_executor,
        {"sql_builder": "sql_builder", END: END},
    )

    compiled = graph.compile()
    logger.info(
        "[TEXT2SQL] Subgraph built: "
        "sql_planner → value_resolver → business_rules → sql_builder → sql_executor"
        " (max 2 retry)"
    )
    return compiled
