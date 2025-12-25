"""
Report Graph

Orchestrates text2sql and visualization graphs to generate complete reports from user messages.

Architecture:
    messages (user input)
        ↓
    extract_query (validate messages)
        ↓
    text2sql (generate SQL and execute)
        ↓
    visualization (decide viz type and build config)
        ↓
    build_response (create final message)
        ↓
    messages (with AI response)
"""

from langgraph.graph import StateGraph, START, END

from .state import ReportState
from .nodes import (
    extract_query_node,
    create_text2sql_node,
    create_visualization_node,
    build_response_node
)


def build_report_graph(text2sql_graph, visualization_graph) -> StateGraph:
    """
    Build the complete report generation graph.

    This graph chains text2sql and visualization graphs together,
    accepting messages as input and producing a complete report.

    Args:
        text2sql_graph: Compiled generic_text2sql graph
        visualization_graph: Compiled data_visualization graph

    Returns:
        Compiled StateGraph for report generation
    """

    # Create graph
    graph = StateGraph(ReportState)

    # Create node factories with graph dependencies
    text2sql_node = create_text2sql_node(text2sql_graph)
    visualization_node = create_visualization_node(visualization_graph)

    # Add nodes
    graph.add_node("extract_query", extract_query_node)
    graph.add_node("text2sql", text2sql_node)
    graph.add_node("visualization", visualization_node)
    graph.add_node("build_response", build_response_node)

    # Define edges
    graph.add_edge(START, "extract_query")
    graph.add_edge("extract_query", "text2sql")
    graph.add_edge("text2sql", "visualization")
    graph.add_edge("visualization", "build_response")
    graph.add_edge("build_response", END)

    # Compile and return
    return graph.compile()
