"""
Text2SQL Subagent Graph (v3)

Serial SemanticIntent flow:

START → create_table → business_rules → semantic_extractor
        → term_resolver → term_validator → schema_builder
        → value_resolver → sql_generator → sql_executor
        ──→ retry on error: sql_executor → semantic_extractor (max 2)
        ──→ cleanup_table → END

Removed: sql_architect, schema_validator, schema_merge (fan-out/fan-in)
Added:   semantic_extractor (LLM intent extraction),
         schema_builder     (deterministic QuerySchema from SemanticIntent)
"""
import logging
import threading
from pathlib import Path
from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.subagents.text2sql.stores import BusinessRulesStore, TermStore
from src.graphs.report_agent.subagents.text2sql.nodes import (
    MAX_RETRY,
    create_business_rules_node,
    create_cleanup_table_node,
    create_create_table_node,
    create_semantic_extractor_node,
    create_schema_builder_node,
    create_sql_executor_node,
    create_sql_generator_node,
    create_term_resolver_node,
    create_term_validator_node,
    create_value_resolver_node,
    init_master_table_background,
    _table_init_event,
    _table_init_started,
)
from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
from src.graphs.report_agent.subagents.text2sql.value_resolver_service import ValueResolverService

logger = logging.getLogger(__name__)


def _route_after_executor(state: dict) -> str:
    """
    Retry routing:
      sql_error set and retry <= MAX_RETRY → semantic_extractor (LLM re-extracts intent)
      Otherwise                            → cleanup_table
    """
    if state.get("sql_error") and state.get("retry_count", 0) <= MAX_RETRY:
        logger.info(f"[TEXT2SQL] Retry {state['retry_count']}/{MAX_RETRY} → semantic_extractor")
        return "semantic_extractor"
    return "cleanup_table"


def build_text2sql_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    connection_string: str,
    business_rules_path: str,
):
    """
    Text2SQL subgraph'ı inşa et (v3 — serial SemanticIntent flow).

    Args:
        llm:                 ChatOpenAI veya uyumlu LLM
        table_name:          Default tablo adı (runtime config override edebilir)
        column_metadata:     {kolon_adı: açıklama} — runtime config override edebilir
        connection_string:   pyodbc / mssql+pyodbc bağlantı string'i
        business_rules_path: business_rules.json dosya yolu
    """
    logger.info(f"[TEXT2SQL] Building subgraph v3 for table: {table_name}")

    # --- Servis başlatma ---
    value_resolver = ValueResolverService(
        db_connection_string=connection_string,
        table_name=table_name,
    )

    _DATA_DIR = Path(__file__).parent.parent.parent / "data" / "vector"

    vector_store = BusinessRulesStore(rules_file_path=business_rules_path)
    vector_store.initialize()

    term_store = TermStore(dict_path=_DATA_DIR / "term_dictionary.json")
    term_store.initialize()

    # --- Node factories ---
    create_table        = create_create_table_node(connection_string, table_name)
    business_rules      = create_business_rules_node(vector_store, llm=llm)
    semantic_extractor  = create_semantic_extractor_node(llm)
    term_resolver       = create_term_resolver_node(term_store, value_resolver)
    term_validator      = create_term_validator_node(llm)
    schema_builder      = create_schema_builder_node()
    value_resolver_node = create_value_resolver_node(value_resolver)
    sql_generator       = create_sql_generator_node(table_name, column_metadata)
    sql_executor        = create_sql_executor_node(connection_string)
    cleanup_table       = create_cleanup_table_node(connection_string, table_name)

    # --- Graph ---
    graph = StateGraph(Text2SQLState)

    graph.add_node("create_table",      create_table)
    graph.add_node("business_rules",    business_rules)
    graph.add_node("semantic_extractor", semantic_extractor)
    graph.add_node("term_resolver",     term_resolver)
    graph.add_node("term_validator",    term_validator)
    graph.add_node("schema_builder",    schema_builder)
    graph.add_node("value_resolver",    value_resolver_node)
    graph.add_node("sql_generator",     sql_generator)
    graph.add_node("sql_executor",      sql_executor)
    graph.add_node("cleanup_table",     cleanup_table)

    # --- Serial flow ---
    graph.add_edge(START,                "create_table")
    graph.add_edge("create_table",       "business_rules")
    graph.add_edge("business_rules",     "semantic_extractor")

    # semantic_extractor → term_resolver (with early-exit for clarification signal)
    def _route_after_semantic_extractor(state: dict):
        if state.get("text2sql_clarification"):
            return END
        return "term_resolver"

    graph.add_conditional_edges(
        "semantic_extractor",
        _route_after_semantic_extractor,
        {END: END, "term_resolver": "term_resolver"},
    )

    graph.add_edge("term_resolver",      "term_validator")
    graph.add_edge("term_validator",     "schema_builder")

    def _route_after_value_resolver(state: dict):
        if state.get("text2sql_clarification"):
            return END
        return "sql_generator"

    graph.add_edge("schema_builder",     "value_resolver")
    graph.add_conditional_edges(
        "value_resolver",
        _route_after_value_resolver,
        {END: END, "sql_generator": "sql_generator"},
    )
    graph.add_edge("sql_generator",      "sql_executor")
    graph.add_conditional_edges(
        "sql_executor",
        _route_after_executor,
        {"semantic_extractor": "semantic_extractor", "cleanup_table": "cleanup_table"},
    )
    graph.add_edge("cleanup_table",      END)

    compiled = graph.compile()
    logger.info(
        "[TEXT2SQL] Subgraph v3 built: "
        "create_table → business_rules → semantic_extractor → term_resolver "
        "→ term_validator → schema_builder → value_resolver "
        "→ sql_generator → sql_executor → cleanup_table (max 2 retry via semantic_extractor)"
    )

    # --- Background table creation at init time (runs only once per process) ---
    if not _table_init_started:
        sql_file = Path(__file__).parent / "master_table_creation.sql"
        if sql_file.exists():
            sql_script = sql_file.read_text(encoding="utf-8")
            logger.info(f"[TEXT2SQL] Starting background table creation ({len(sql_script)} chars)")
            init_thread = threading.Thread(
                target=init_master_table_background,
                args=(connection_string, table_name, sql_script),
                daemon=True,
            )
            init_thread.start()
        else:
            logger.warning(f"[TEXT2SQL] SQL file not found at {sql_file}, skipping background init")
            _table_init_event.set()
    else:
        logger.info("[TEXT2SQL] Background table init already started, skipping")

    return compiled
