"""
Visualization Subagent — Graph

START → data_analyzer → viz_decider → [conditional]
  ├── needs_graph=True  → chart_generator → response_builder → END
  └── needs_graph=False → response_builder → END
"""
import logging

from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.subagents.visualization.nodes import (
    data_analyzer_node,
    create_viz_decider_node,
    create_chart_generator_node,
    response_builder_node,
)
from src.graphs.report_agent.subagents.visualization.state import VisualizationState

logger = logging.getLogger(__name__)


def _route_after_decider(state: dict) -> str:
    """needs_graph=True → chart_generator, False → response_builder."""
    viz = state.get("viz_decision") or {}
    if viz.get("needs_graph", False):
        return "chart_generator"
    return "response_builder"


def build_visualization_graph(llm):
    """
    Visualization subagent graph.

    4 node, 1 conditional edge, max 2 LLM çağrısı/tur.
    ReportState ile shared-state pattern üzerinden çalışır.
    """
    graph = StateGraph(VisualizationState)

    graph.add_node("data_analyzer", data_analyzer_node)
    graph.add_node("viz_decider", create_viz_decider_node(llm))
    graph.add_node("chart_generator", create_chart_generator_node(llm))
    graph.add_node("response_builder", response_builder_node)

    graph.add_edge(START, "data_analyzer")
    graph.add_edge("data_analyzer", "viz_decider")
    graph.add_conditional_edges(
        "viz_decider",
        _route_after_decider,
        {"chart_generator": "chart_generator", "response_builder": "response_builder"},
    )
    graph.add_edge("chart_generator", "response_builder")
    graph.add_edge("response_builder", END)

    compiled = graph.compile()
    logger.info("[VISUALIZATION] Built: 4 nodes, max 2 LLM calls/turn")
    return compiled
