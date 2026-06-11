# tests/graphs/report/insight_engine/test_summary_granularity.py
import pandas as pd
import asyncio


def test_summary_has_daily_granularity():
    from src.graphs.report_agent.nodes import _fetch_summary_stats
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    df = pd.DataFrame({
        "DocumentDate": dates,
        "ProductName": ["A"] * 10,
        "RowAmount": [100.0] * 10,
    })
    result = asyncio.run(_fetch_summary_stats(
        connection_string="dummy",
        active_sql="SELECT * FROM T WHERE DocumentDate BETWEEN '2024-01-01' AND '2024-01-10'",
        df=df,
        dim_columns=["DocumentDate", "ProductName"],
        metric_columns=["RowAmount"],
    ))
    assert result.get("data_granularity") == "günlük"
    assert "groupby_fields" in result
    assert "ProductName" in result["groupby_fields"]


def test_summary_has_groupby_fields_without_date():
    from src.graphs.report_agent.nodes import _fetch_summary_stats
    df = pd.DataFrame({
        "ProductName": ["A", "B", "C"],
        "RowAmount": [100.0, 200.0, 300.0],
    })
    result = asyncio.run(_fetch_summary_stats(
        connection_string="dummy",
        active_sql="",
        df=df,
        dim_columns=["ProductName"],
        metric_columns=["RowAmount"],
    ))
    assert "groupby_fields" in result
    assert result["groupby_fields"] == ["ProductName"]
    assert result.get("data_granularity") in ("bilinmiyor", None, "")


def test_general_table_shows_granularity():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    ctx = AnalysisContext(
        user_query="t", active_filters=[], period_label="test",
        dimension_columns=["ProductName"], metric_columns=["RowAmount"],
        summary={
            "primary_metric": "RowAmount",
            "total": 1000000.0,
            "period_days": 30,
            "daily_avg": 33333.0,
            "segment_col": "ProductName",
            "segment_count": 20,
            "top_segment": "LATTE",
            "top_segment_share_pct": 30.6,
            "data_granularity": "günlük",
            "groupby_fields": ["ProductName"],
        },
    )
    table = LLMInterpreter(None)._build_general_table(ctx)
    assert "günlük" in table
    assert "ProductName" in table
