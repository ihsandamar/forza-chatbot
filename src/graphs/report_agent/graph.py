"""
Report Agent — Ana Graph

START → classify_intent → [intent_router]
  ├── NEW_QUERY      → text2sql → visualization → build_response → END
  ├── MODIFY_QUERY   → modify_sql → text2sql → visualization → build_response → END
  ├── USE_RESULT(A)  → extract_entity → text2sql → visualization → build_response → END
  └── USE_RESULT(B)  → visualization → build_response → END
"""
import logging
from typing import Any, Dict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.nodes import (
    build_response_node,
    create_classify_intent_node,
    create_extract_entity_node,
    create_modify_sql_node,
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
    if intent == "USE_RESULT":
        return "visualization" if state.get("use_result_type") == "revisualize" else "extract_entity"
    return "text2sql"  # NEW_QUERY + fallback


def build_report_agent_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    business_rules: Dict[str, Any],
    connection_string: str,
    checkpointer=None,
):
    text2sql = build_text2sql_graph(llm, table_name, column_metadata, business_rules, connection_string)
    visualization = build_visualization_graph(llm)

    graph = StateGraph(ReportState)

    graph.add_node("classify_intent", create_classify_intent_node(llm))
    graph.add_node("modify_sql", create_modify_sql_node(llm, column_metadata))
    graph.add_node("extract_entity", create_extract_entity_node(llm))
    graph.add_node("text2sql", text2sql)
    graph.add_node("visualization", visualization)
    graph.add_node("build_response", build_response_node)

    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        _intent_router,
        {
            "text2sql": "text2sql",
            "modify_sql": "modify_sql",
            "extract_entity": "extract_entity",
            "visualization": "visualization",
        },
    )
    graph.add_edge("modify_sql", "text2sql")
    graph.add_edge("extract_entity", "text2sql")
    graph.add_edge("text2sql", "visualization")
    graph.add_edge("visualization", "build_response")
    graph.add_edge("build_response", END)

    compiled = graph.compile(checkpointer=checkpointer or MemorySaver())
    logger.info("[REPORT_AGENT] Built: 6 nodes, max 2 LLM calls/turn")
    return compiled
