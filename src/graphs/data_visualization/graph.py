# data_visualization/graph.py

from langgraph.graph import StateGraph, END
from src.models.llm import LLM
from .state import DataVisualizationState
from .nodes.state_transformer import state_transformer_node
from .nodes.data_analyzer import data_analyzer_node
from .nodes.visualization_decider import create_visualization_decider_node
from .nodes.chart_config_builder import chart_config_builder_node
from .nodes.plotly_code_generator import create_plotly_code_generator_node
from .nodes.html_snippet_generator import html_snippet_generator_node
from .nodes.response_builder import response_builder_node


def should_continue(state: DataVisualizationState) -> str:
    """Check for errors"""
    if state.get("error"):
        return END
    return "continue"


def build_visualization_graph(llm: LLM) -> StateGraph:
    """Build the complete visualization graph"""

    graph = StateGraph(DataVisualizationState)

    # Create LLM-based nodes
    visualization_decider_node = create_visualization_decider_node(llm)
    plotly_code_generator_node = create_plotly_code_generator_node(llm)

    # Add nodes
    graph.add_node("transform_state", state_transformer_node)
    graph.add_node("analyze_data", data_analyzer_node)
    graph.add_node("decide_visualization", visualization_decider_node)
    graph.add_node("build_chart_config", chart_config_builder_node)
    graph.add_node("generate_plotly", plotly_code_generator_node)
    graph.add_node("generate_html_snippet", html_snippet_generator_node)
    graph.add_node("build_response", response_builder_node)

    # Set entry point
    graph.set_entry_point("transform_state")

    # Add edges
    graph.add_edge("transform_state", "analyze_data")
    graph.add_edge("analyze_data", "decide_visualization")
    graph.add_edge("decide_visualization", "build_chart_config")
    graph.add_edge("build_chart_config", "generate_plotly")
    graph.add_edge("generate_plotly", "generate_html_snippet")
    graph.add_edge("generate_html_snippet", "build_response")
    graph.add_edge("build_response", END)

    return graph.compile()