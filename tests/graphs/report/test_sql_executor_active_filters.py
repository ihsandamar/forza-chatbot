import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from src.graphs.report_agent.subagents.text2sql.nodes import create_sql_executor_node


@pytest.fixture
def mock_results():
    return [{"BranchName": "Ankara", "ToplamCiro": 1000.0}]


def test_active_filters_populated_from_query_schema(mock_results):
    """sql_executor_node active_filters'ı query_schema'dan okumalı, query_plan'dan değil."""
    state = {
        "sql_queries": ["SELECT [BranchName], SUM([RowAmount]) FROM [T] WHERE [BranchName] = 'Ankara'"],
        "retry_count": 0,
        "query_schema": {
            "filters": [
                {
                    "column": "BranchName",
                    "operator": "=",
                    "value": "Ankara",
                    "resolved_value": "Ankara",
                    "value_hint": "ankara",
                    "date_descriptor": None,
                }
            ]
        },
    }

    with patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._execute_sql_async",
        new=AsyncMock(return_value=mock_results),
    ):
        node = create_sql_executor_node("mssql+pyodbc://dummy")
        result = asyncio.run(node(state))

    assert result["active_filters"] == [{"field": "BranchName", "value": "Ankara"}]
    assert result["error"] is None


def test_active_filters_excludes_date_filters(mock_results):
    """Tarih filtreleri active_filters'a girmemeli — LLM için gereksiz gürültü."""
    state = {
        "sql_queries": ["SELECT * FROM [T]"],
        "retry_count": 0,
        "query_schema": {
            "filters": [
                {
                    "column": "DocumentDate",
                    "operator": ">=",
                    "date_descriptor": {"type": "relative", "unit": "year", "amount": -1},
                    "value": None,
                    "resolved_value": None,
                    "value_hint": "son 1 yıl",
                },
                {
                    "column": "BranchName",
                    "operator": "=",
                    "value": "Istanbul",
                    "resolved_value": "Istanbul",
                    "value_hint": "istanbul",
                    "date_descriptor": None,
                },
            ]
        },
    }

    with patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._execute_sql_async",
        new=AsyncMock(return_value=mock_results),
    ):
        node = create_sql_executor_node("mssql+pyodbc://dummy")
        result = asyncio.run(node(state))

    assert result["active_filters"] == [{"field": "BranchName", "value": "Istanbul"}]


def test_active_filters_empty_when_no_query_schema(mock_results):
    """query_schema yoksa active_filters boş liste olmalı — hata fırlatmamalı."""
    state = {
        "sql_queries": ["SELECT * FROM [T]"],
        "retry_count": 0,
    }

    with patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._execute_sql_async",
        new=AsyncMock(return_value=mock_results),
    ):
        node = create_sql_executor_node("mssql+pyodbc://dummy")
        result = asyncio.run(node(state))

    assert result["active_filters"] == []


def test_sql_executor_preserves_active_filters_when_query_schema_empty(mock_results):
    """
    pre_built_sql yolu: query_schema boş olduğunda sql_executor,
    state'deki mevcut active_filters'ı korumalı (üzerine [] yazmamalı).
    """
    state = {
        "sql_queries": ["SELECT [BranchName], SUM([RowAmount]) FROM T WHERE [CategoryName]='Dürüm' AND [BranchName]='Ankara' GROUP BY [BranchName]"],
        "query_schema": None,  # pre_built_sql bypass: query_schema YOK
        "active_filters": [   # modify_sql_node tarafından güncellenmiş
            {"field": "CategoryName", "value": "Dürüm"},
            {"field": "BranchName", "value": "Ankara"},
        ],
        "accumulated_entities": None,
        "retry_count": 0,
    }

    with patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._execute_sql_async",
        new=AsyncMock(return_value=mock_results),
    ):
        node = create_sql_executor_node("mssql+pyodbc://dummy")
        result = asyncio.run(node(state))

    assert result.get("error") is None
    filters = result.get("active_filters", [])
    fields = {f["field"] for f in filters}
    assert "CategoryName" in fields, "CategoryName filtresi korunmalıydı"
    assert "BranchName" in fields, "BranchName filtresi korunmalıydı"
