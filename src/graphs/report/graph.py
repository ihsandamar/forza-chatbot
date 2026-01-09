"""
Report Graph

Orchestrates text2sql and visualization graphs to generate complete reports from user messages.

Architecture (OPTIMIZED FOR STREAMING):
    messages (user input)
        ↓
    immediate_ack (instant response - "İşleniyor...")
        ↓
    extract_query (validate messages)
        ↓
    text2sql (generate SQL and execute)
        ↓
    check_results (skip visualization if no records)
        ├─→ visualization (if has data)
        │       ↓
        └─→ build_response (if no data or after viz)
        ↓
    messages (with AI response)
"""

from langgraph.graph import StateGraph, START, END

from .state import ReportState
from .nodes import (
    immediate_acknowledgment_node,
    extract_query_node,
    check_results_node,
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

    # Add nodes (OPTIMIZED: immediate_ack added for instant response)
    graph.add_node("immediate_ack", immediate_acknowledgment_node)
    graph.add_node("extract_query", extract_query_node)
    graph.add_node("text2sql", text2sql_node)
    graph.add_node("check_results", check_results_node)
    graph.add_node("visualization", visualization_node)
    graph.add_node("build_response", build_response_node)

    # Define conditional routing function
    def should_visualize(state: ReportState) -> str:
        """Route to visualization only if records exist"""
        if state.get("no_records_message"):
            return "build_response"
        return "visualization"

    # Define edges (OPTIMIZED: immediate_ack runs first)
    graph.add_edge(START, "immediate_ack")
    graph.add_edge("immediate_ack", "extract_query")
    graph.add_edge("extract_query", "text2sql")
    graph.add_edge("text2sql", "check_results")
    # Conditional edge: check_results -> visualization or build_response
    graph.add_conditional_edges("check_results", should_visualize)
    graph.add_edge("visualization", "build_response")
    graph.add_edge("build_response", END)

    # Compile and return
    return graph.compile()
