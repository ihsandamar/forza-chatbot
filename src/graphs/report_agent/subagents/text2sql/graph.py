"""
Text2SQL Subagent Graph (v2.2)

START → create_table → business_rules → term_resolver
        ├── sql_architect (LLM)    ──┐
        ├── schema_validator (LLM) ──┼→ schema_merge → value_resolver
        └── term_validator (LLM)   ──┘
        → sql_generator → sql_executor ──────────────────────────────┐
                               ↑ (retry, max 2)                      │
                               └─────────────────────────────────────┘
                                                                      ↓
                                                          cleanup_table → END

term_validator: Parallel LLM gate — filter adaylarını onaylar/reddeder.
sql_generator: validated_term_filters okur. LLM yok.
"""
import logging
from pathlib import Path
from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.subagents.text2sql.business_rules_vector_store import BusinessRulesVectorStore
from src.graphs.report_agent.subagents.text2sql.term_vector_store import TermVectorStore
from src.graphs.report_agent.subagents.text2sql.nodes import (
    MAX_RETRY,
    create_business_rules_node,
    create_cleanup_table_node,
    create_create_table_node,
    create_schema_validator_node,
    create_sql_architect_node,
    create_sql_executor_node,
    create_sql_generator_node,
    create_term_resolver_node,
    create_term_validator_node,   # ADD
    create_value_resolver_node,
    schema_merge_node,
)
from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
from src.graphs.report_agent.subagents.text2sql.value_resolver_service import ValueResolverService

logger = logging.getLogger(__name__)


def _route_after_executor(state: dict) -> str:
    """
    Retry routing:
      sql_error set ve retry < MAX_RETRY → sql_architect (LLM yeniden şema üretir)
      Aksi halde → cleanup_table
    """
    if state.get("sql_error") and state.get("retry_count", 0) <= MAX_RETRY:
        logger.info(f"[TEXT2SQL] Retry {state['retry_count']}/{MAX_RETRY} → sql_architect")
        return "sql_architect"
    return "cleanup_table"


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
        llm:                 ChatOpenAI veya uyumlu LLM
        table_name:          Default tablo adı (runtime config override edebilir)
        column_metadata:     {kolon_adı: açıklama} — runtime config override edebilir
        connection_string:   pyodbc / mssql+pyodbc bağlantı string'i
        business_rules_path: business_rules.json dosya yolu
        chroma_persist_dir:  ChromaDB persist klasörü
    """
    logger.info(f"[TEXT2SQL] Building subgraph v2.2 for table: {table_name}")

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

    # Collections boşsa index'i oluştur (ilk çalışma veya chroma_dir temizlendiyse)
    if vector_store.rules_collection.count() == 0:
        logger.info("[TEXT2SQL] ChromaDB collections empty, building index...")
        vector_store.index_rules()

    # --- Node factories ---
    create_table        = create_create_table_node(connection_string, table_name)
    business_rules      = create_business_rules_node(vector_store, llm=llm)
    term_vector_store = TermVectorStore(
        dict_path=Path(__file__).parent / "term_dictionary.json",
        persist_directory=chroma_persist_dir,
    )
    term_vector_store.initialize()

    term_resolver       = create_term_resolver_node(term_vector_store)
    term_validator      = create_term_validator_node(llm)
    sql_architect       = create_sql_architect_node(llm, column_metadata)
    schema_validator    = create_schema_validator_node(llm, column_metadata)
    value_resolver_node = create_value_resolver_node(value_resolver)
    sql_generator       = create_sql_generator_node(table_name)
    sql_executor        = create_sql_executor_node(connection_string)
    cleanup_table       = create_cleanup_table_node(connection_string, table_name)

    # --- Graph ---
    graph = StateGraph(Text2SQLState)

    graph.add_node("create_table",      create_table)
    graph.add_node("business_rules",    business_rules)
    graph.add_node("term_resolver",     term_resolver)
    graph.add_node("term_validator",    term_validator)
    graph.add_node("sql_architect",     sql_architect)
    graph.add_node("schema_validator",  schema_validator)
    graph.add_node("schema_merge",      schema_merge_node)
    graph.add_node("value_resolver",    value_resolver_node)
    graph.add_node("sql_generator",     sql_generator)
    graph.add_node("sql_executor",      sql_executor)
    graph.add_node("cleanup_table",     cleanup_table)

    graph.add_edge(START,               "create_table")
    graph.add_edge("create_table",      "business_rules")
    graph.add_edge("business_rules",    "term_resolver")

    # Fan-out: term_resolver → sql_architect + schema_validator + term_validator (paralel)
    graph.add_edge("term_resolver",     "sql_architect")
    graph.add_edge("term_resolver",     "schema_validator")
    graph.add_edge("term_resolver",     "term_validator")

    # Fan-in: üçü tamamlandığında → schema_merge
    graph.add_edge("sql_architect",     "schema_merge")
    graph.add_edge("schema_validator",  "schema_merge")
    graph.add_edge("term_validator",    "schema_merge")

    graph.add_edge("schema_merge",      "value_resolver")
    graph.add_edge("value_resolver",    "sql_generator")
    graph.add_edge("sql_generator",     "sql_executor")
    graph.add_conditional_edges(
        "sql_executor",
        _route_after_executor,
        {"sql_architect": "sql_architect", "cleanup_table": "cleanup_table"},
    )
    graph.add_edge("cleanup_table",     END)

    compiled = graph.compile()
    logger.info(
        "[TEXT2SQL] Subgraph v2.2 built: "
        "create_table → business_rules → term_resolver "
        "→ [sql_architect ∥ schema_validator ∥ term_validator] → schema_merge "
        "→ value_resolver → sql_generator → sql_executor → cleanup_table (max 2 retry)"
    )
    return compiled
