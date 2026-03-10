"""
Visualization V2 — Graph Definition

START -> data_analyzer -> viz_decider -> spec_validator -> [conditional]
  +-- needs_graph=True  -> template_renderer -> response_builder -> END
  +-- needs_graph=False -> response_builder -> END
"""
import logging

from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.subagents.visualization_v2.nodes import (
    data_analyzer_node,
    create_viz_decider_node,
    spec_validator_node,
    template_renderer_node,
    response_builder_node,
)
from src.graphs.report_agent.subagents.visualization_v2.state import VisualizationState

logger = logging.getLogger(__name__)


def _route_after_validator(state: dict) -> str:
    viz = state.get("viz_decision") or {}
    if viz.get("needs_graph", False):
        return "template_renderer"
    return "response_builder"


def build_visualization_graph(llm):
    """
    Visualization V2 subagent graph.

    5 nodes, 1 conditional edge, max 1 LLM call/turn.
    Karar katmani: data_analyzer -> viz_decider -> spec_validator
    Cizim katmani: template_renderer -> response_builder
    """
    graph = StateGraph(VisualizationState)

    graph.add_node("data_analyzer", data_analyzer_node)
    graph.add_node("viz_decider", create_viz_decider_node(llm))
    graph.add_node("spec_validator", spec_validator_node)
    graph.add_node("template_renderer", template_renderer_node)
    graph.add_node("response_builder", response_builder_node)

    graph.add_edge(START, "data_analyzer")
    graph.add_edge("data_analyzer", "viz_decider")
    graph.add_edge("viz_decider", "spec_validator")
    graph.add_conditional_edges(
        "spec_validator",
        _route_after_validator,
        {"template_renderer": "template_renderer", "response_builder": "response_builder"},
    )
    graph.add_edge("template_renderer", "response_builder")
    graph.add_edge("response_builder", END)

    compiled = graph.compile()
    logger.info("[V2:VISUALIZATION] Built: 5 nodes, max 1 LLM call/turn")
    return compiled
