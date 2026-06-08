import asyncio
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch


def test_insight_node_returns_insight_output():
    from src.graphs.report_agent.nodes import create_insight_engine_node

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="Test insight çıktısı."))

    state = {
        "user_query": "insight ver",
        "active_results": [
            {"ProductName": "Burger", "RowAmount": 1250.0},
            {"ProductName": "Pizza", "RowAmount": 2000.0},
            {"ProductName": "Salad", "RowAmount": 500.0},
            {"ProductName": "Wrap", "RowAmount": 100.0},
            {"ProductName": "Soup", "RowAmount": 4500.0},
        ],
        "active_sql": "SELECT ProductName, SUM(RowAmount) FROM T WHERE DocumentDate BETWEEN '2024-01-01' AND '2024-01-31' GROUP BY ProductName",
        "active_filters": [],
        "comparison_sql": None,
        "semantic_intent": {"time": {"granularity": "monthly"}},
        "visualization_output": None,
    }

    with patch(
        "src.graphs.report_agent.insight_engine.fetcher.ComparisonDataFetcher.fetch",
        new=AsyncMock(return_value=pd.DataFrame()),
    ):
        node = create_insight_engine_node(mock_llm, "mssql+pyodbc://test")
        result = asyncio.run(node(state))

    assert "insight_output" in result
    assert isinstance(result["insight_output"], str)
    assert len(result["insight_output"]) > 0
    assert "insight_findings" in result


def test_insight_node_no_active_results():
    import asyncio
    from src.graphs.report_agent.nodes import create_insight_engine_node
    mock_llm = MagicMock()
    state = {
        "user_query": "insight ver",
        "active_results": None,
        "active_sql": None,
        "active_filters": [],
        "comparison_sql": None,
        "semantic_intent": None,
        "visualization_output": None,
    }
    node = create_insight_engine_node(mock_llm, "mssql+pyodbc://test")
    result = asyncio.run(node(state))
    assert "insight_output" in result
    assert result["insight_output"] is not None
