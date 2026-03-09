"""
Report Agent — Ana Graph

START → classify_intent → [intent_router]
  ├── NEW_QUERY          → text2sql → visualization → build_response → END
  ├── MODIFY_QUERY       → modify_sql → text2sql → visualization → build_response → END
  ├── USE_RESULT(A)      → extract_entity → text2sql → visualization → build_response → END
  ├── USE_RESULT(B)      → visualization → build_response → END
  ├── USE_RESULT(compute)→ compute_results → build_response → END
  ├── USE_RESULT(modify) → extract_entity → modify_sql → text2sql → ...
  └── VAGUE_QUERY        → report_chat → classify_intent (loop, max 2)
"""
import logging
from typing import Any, Dict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.configuration import ReportAgentConfiguration
from src.graphs.report_agent.nodes import (
    build_response_node,
    create_classify_intent_node,
    create_compute_results_node,
    create_extract_entity_node,
    create_modify_sql_node,
    create_report_chat_node,
)
from src.graphs.report_agent.state import ReportState
from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph
from src.graphs.report_agent.subagents.visualization.graph import build_visualization_graph

logger = logging.getLogger(__name__)


def _intent_router(state: dict) -> str:
    """Pure function — test edilebilir routing."""
    intent = state.get("intent_type", "NEW_QUERY")
    if intent == "MODIFY_QUERY":
        return "modify_sql"
    if intent == "VAGUE_QUERY":
        return "report_chat"
    if intent == "USE_RESULT":
        use_result = state.get("use_result_type")
        if use_result == "revisualize":
            return "visualization"
        if use_result == "compute":
            return "compute_results"
        return "extract_entity"  # new_query + modify_context
    return "text2sql"  # NEW_QUERY + fallback


def _after_extract_entity_router(state: dict) -> str:
    """extract_entity sonrası: modify_context → modify_sql, diğerleri → text2sql."""
    return "modify_sql" if state.get("use_result_type") == "modify_context" else "text2sql"


def _visualization_router(state: dict) -> str:
    """text2sql sonrası: grafik istendiyse visualization, istenmemişse direkt build_response."""
    return "visualization" if state.get("wants_visualization", False) else "build_response"


def build_report_agent_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    connection_string: str,
    business_rules_path: str,
    chroma_persist_dir: str,
    checkpointer=None,
):
    # business_rules_path artık ReportAgentConfiguration.business_rules_path default'u ile
    # Studio'dan override edilebilir.
    default_br_path = ReportAgentConfiguration.model_fields["business_rules_path"].default
    effective_business_rules_path = business_rules_path or default_br_path

    text2sql = build_text2sql_graph(
        llm,
        table_name,
        column_metadata,
        connection_string,
        effective_business_rules_path,
        chroma_persist_dir,
    )
    visualization = build_visualization_graph(llm)

    graph = StateGraph(ReportState, config_schema=ReportAgentConfiguration)

    graph.add_node("classify_intent", create_classify_intent_node(llm))
    graph.add_node("modify_sql", create_modify_sql_node(llm, column_metadata))
    graph.add_node("extract_entity", create_extract_entity_node(llm))
    graph.add_node("compute_results", create_compute_results_node(llm))
    graph.add_node("report_chat", create_report_chat_node(llm, column_metadata))
    graph.add_node("text2sql", text2sql)
    graph.add_node("visualization", visualization)
    graph.add_node("build_response", build_response_node)

    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        _intent_router,
        {
            "text2sql":        "text2sql",
            "modify_sql":      "modify_sql",
            "extract_entity":  "extract_entity",
            "visualization":   "visualization",
            "compute_results": "compute_results",
            "report_chat":     "report_chat",
        },
    )
    graph.add_edge("modify_sql", "text2sql")
    graph.add_edge("report_chat", "classify_intent")
    graph.add_conditional_edges(
        "extract_entity",
        _after_extract_entity_router,
        {
            "modify_sql": "modify_sql",
            "text2sql":   "text2sql",
        },
    )
    graph.add_edge("compute_results", "build_response")
    graph.add_conditional_edges(
        "text2sql",
        _visualization_router,
        {"visualization": "visualization", "build_response": "build_response"},
    )
    graph.add_edge("visualization", "build_response")
    graph.add_edge("build_response", END)

    # When checkpointer is explicitly False, compile without one (for use as subgraph
    # where the parent's checkpointer handles state and interrupt propagation).
    if checkpointer is False:
        compiled = graph.compile()
    else:
        compiled = graph.compile(checkpointer=checkpointer or MemorySaver())
    logger.info("[REPORT_AGENT] Built: 8 nodes, report_chat=VAGUE_QUERY loop")
    return compiled
