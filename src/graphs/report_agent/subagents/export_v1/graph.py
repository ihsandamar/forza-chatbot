import logging

from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.subagents.export_v1.nodes import (
    export_decider_node,
    export_response_builder_node,
    format_renderer_node,
)
from src.graphs.report_agent.subagents.export_v1.state import ExportState

logger = logging.getLogger(__name__)


def build_export_graph():
    graph = StateGraph(ExportState)
    graph.add_node("export_decider", export_decider_node)
    graph.add_node("format_renderer", format_renderer_node)
    graph.add_node("response_builder", export_response_builder_node)

    graph.add_edge(START, "export_decider")
    graph.add_edge("export_decider", "format_renderer")
    graph.add_edge("format_renderer", "response_builder")
    graph.add_edge("response_builder", END)

    compiled = graph.compile()
    logger.info("[EXPORT_V1] Built: 3 nodes, 0 LLM calls")
    return compiled
