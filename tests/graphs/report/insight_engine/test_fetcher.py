"""
Tests for ComparisonDataFetcher — Mode A (auto-shift) and Mode B (user SQL).
"""
import pandas as pd
from unittest.mock import AsyncMock, patch


def test_mode_a_shifts_dates():
    """Test that Mode A shifts dates correctly."""
    from src.graphs.report_agent.insight_engine.fetcher import ComparisonDataFetcher
    sql = "SELECT ProductName, SUM(RowAmount) FROM T WHERE DocumentDate BETWEEN '2024-01-01' AND '2024-01-31' GROUP BY ProductName"
    shifted = ComparisonDataFetcher._shift_sql_dates(sql)
    # 31-day range → December 2023
    assert "2023-12-01" in shifted
    assert "2023-12-31" in shifted


def test_mode_a_no_date_returns_none():
    """Test that Mode A returns None when no date found."""
    from src.graphs.report_agent.insight_engine.fetcher import ComparisonDataFetcher
    sql = "SELECT * FROM T WHERE BranchName = 'Ankara'"
    assert ComparisonDataFetcher._shift_sql_dates(sql) is None


def test_mode_b_uses_comparison_sql():
    """Test that Mode B uses user-provided comparison_sql."""
    from src.graphs.report_agent.insight_engine.fetcher import ComparisonDataFetcher
    state = {
        "active_sql": "SELECT * FROM T WHERE DocumentDate BETWEEN '2024-01-01' AND '2024-01-31'",
        "comparison_sql": "SELECT * FROM T WHERE DocumentDate BETWEEN '2023-01-01' AND '2023-01-31'",
    }
    fetcher = ComparisonDataFetcher(connection_string="mssql+pyodbc://test")
    sql = fetcher._resolve_comparison_sql(state)
    assert sql == state["comparison_sql"]


def test_mode_a_selected_when_no_comparison_sql():
    """Test that Mode A is selected when comparison_sql is not provided."""
    from src.graphs.report_agent.insight_engine.fetcher import ComparisonDataFetcher
    state = {
        "active_sql": "SELECT * FROM T WHERE DocumentDate BETWEEN '2024-01-01' AND '2024-01-31'",
    }
    fetcher = ComparisonDataFetcher(connection_string="mssql+pyodbc://test")
    sql = fetcher._resolve_comparison_sql(state)
    assert sql is not None
    assert "2023-12-01" in sql
