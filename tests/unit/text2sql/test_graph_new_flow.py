"""
Tests for the new text2sql graph flow (v3).

Verifies:
- graph builds without schema_validator / sql_architect / schema_merge nodes
- new semantic_extractor and schema_builder nodes are present
- _route_after_executor routes errors to semantic_extractor, not sql_architect
"""
import pytest


def test_graph_builds_without_schema_validator():
    """build_text2sql_graph succeeds and does not register schema_validator node."""
    from unittest.mock import MagicMock, patch
    from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = MagicMock()

    with patch("src.graphs.report_agent.subagents.text2sql.graph.TermStore") as MockTermStore, \
         patch("src.graphs.report_agent.subagents.text2sql.graph.BusinessRulesStore") as MockBRStore, \
         patch("src.graphs.report_agent.subagents.text2sql.graph.ValueResolverService") as MockVR, \
         patch("src.graphs.report_agent.subagents.text2sql.graph._table_init_started", True):
        MockTermStore.return_value.initialize.return_value = None
        MockBRStore.return_value.initialize.return_value = None
        compiled = build_text2sql_graph(
            llm=mock_llm,
            table_name="TestTable",
            column_metadata={"RowAmount": "Satış tutarı"},
            connection_string="mssql+pyodbc://...",
            business_rules_path="dummy.json",
        )
    assert compiled is not None
    node_names = list(compiled.get_graph().nodes.keys())
    assert "semantic_extractor" in node_names
    assert "schema_builder" in node_names
    assert "schema_validator" not in node_names
    assert "sql_architect" not in node_names
    assert "schema_merge" not in node_names


def test_retry_routes_to_semantic_extractor():
    """On sql_error, graph routes to semantic_extractor not sql_architect."""
    from src.graphs.report_agent.subagents.text2sql.graph import _route_after_executor
    state = {"sql_error": "Invalid column name 'X'", "retry_count": 1}
    assert _route_after_executor(state) == "semantic_extractor"


def test_no_error_routes_to_cleanup_table():
    """Without sql_error, graph routes to cleanup_table."""
    from src.graphs.report_agent.subagents.text2sql.graph import _route_after_executor
    state = {"sql_error": None, "retry_count": 0}
    assert _route_after_executor(state) == "cleanup_table"


def test_max_retry_exceeded_routes_to_cleanup_table():
    """When retry_count exceeds MAX_RETRY, routes to cleanup_table."""
    from src.graphs.report_agent.subagents.text2sql.graph import _route_after_executor, MAX_RETRY
    state = {"sql_error": "Some error", "retry_count": MAX_RETRY + 1}
    assert _route_after_executor(state) == "cleanup_table"
