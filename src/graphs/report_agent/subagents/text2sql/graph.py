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
    create_schema_validator_node,
    create_sql_architect_node,
    create_sql_executor_node,
    create_sql_generator_node,
    create_term_resolver_node,
    create_term_validator_node,
    create_value_resolver_node,
    schema_merge_node,
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
):
    """
    Text2SQL subgraph'ı inşa et.

    Args:
        llm:                 ChatOpenAI veya uyumlu LLM
        table_name:          Default tablo adı (runtime config override edebilir)
        column_metadata:     {kolon_adı: açıklama} — runtime config override edebilir
        connection_string:   pyodbc / mssql+pyodbc bağlantı string'i
        business_rules_path: business_rules.json dosya yolu
    """
    logger.info(f"[TEXT2SQL] Building subgraph v2.2 for table: {table_name}")

    # --- Servis başlatma ---
    value_resolver = ValueResolverService(
        db_connection_string=connection_string,
        table_name=table_name,
    )

    _DATA_DIR = Path(__file__).parent.parent.parent / "data" / "vector"

    vector_store = BusinessRulesStore(rules_file_path=business_rules_path)
    vector_store.initialize()
    business_rules = create_business_rules_node(vector_store, llm=llm)

    term_store = TermStore(dict_path=_DATA_DIR / "term_dictionary.json")
    term_store.initialize()
    term_resolver = create_term_resolver_node(term_store)

    # --- Node factories ---
    create_table        = create_create_table_node(connection_string, table_name)
    term_validator      = create_term_validator_node(llm)
    sql_architect       = create_sql_architect_node(llm, column_metadata)
    schema_validator    = create_schema_validator_node(llm, column_metadata)
    value_resolver_node = create_value_resolver_node(value_resolver)
    sql_generator       = create_sql_generator_node(table_name, column_metadata)
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
    # With early-exit for text2sql_clarification signal
    def _route_after_term_resolver(state: dict):
        """Clarification sinyali varsa END, yoksa fan-out."""
        if state.get("text2sql_clarification"):
            return END
        return ["sql_architect", "schema_validator", "term_validator"]

    graph.add_conditional_edges("term_resolver", _route_after_term_resolver)

    # Fan-in: üçü tamamlandığında → schema_merge
    graph.add_edge("sql_architect",     "schema_merge")
    graph.add_edge("schema_validator",  "schema_merge")
    graph.add_edge("term_validator",    "schema_merge")

    graph.add_edge("schema_merge",      "value_resolver")

    def _route_after_value_resolver(state: dict):
        """Clarification sinyali varsa END, yoksa sql_generator."""
        if state.get("text2sql_clarification"):
            return END
        return "sql_generator"

    graph.add_conditional_edges(
        "value_resolver",
        _route_after_value_resolver,
        {END: END, "sql_generator": "sql_generator"},
    )
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
