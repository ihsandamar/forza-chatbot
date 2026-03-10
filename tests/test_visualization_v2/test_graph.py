"""Graph compilation and routing tests."""
import pytest


def test_graph_compiles():
    """Graph should compile without errors using a mock LLM."""
    from unittest.mock import MagicMock
    from src.graphs.report_agent.subagents.visualization_v2.graph import build_visualization_graph

    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=mock_llm)

    graph = build_visualization_graph(mock_llm)
    assert graph is not None


def test_graph_has_5_nodes():
    from unittest.mock import MagicMock
    from src.graphs.report_agent.subagents.visualization_v2.graph import build_visualization_graph

    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=mock_llm)

    graph = build_visualization_graph(mock_llm)
    # StateGraph compiled graph has nodes attribute
    node_names = set(graph.get_graph().nodes.keys())
    expected = {"data_analyzer", "viz_decider", "spec_validator", "template_renderer", "response_builder"}
    assert expected.issubset(node_names)
