# tests/graphs/report/insight_engine/analyzers/test_trend_mk.py
import pandas as pd
import numpy as np


def _make_ts_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="trend",
        active_filters=[],
        period_label="test",
        dimension_columns=["DocumentDate"],
        metric_columns=["RowAmount"],
    )


def test_mk_trend_in_extra_for_time_series():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    df = pd.DataFrame({
        "DocumentDate": pd.date_range("2024-01-01", periods=10),
        "RowAmount": [100, 110, 120, 130, 140, 150, 160, 170, 180, 190],
    })
    findings = TrendAnalyzer().analyze(df, pd.DataFrame(), _make_ts_ctx())
    assert len(findings) == 1
    extra = findings[0].extra
    assert "mk_trend" in extra
    assert "mk_tau" in extra
    assert "sens_slope" in extra


def test_mk_trend_increasing_for_monotone_series():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    df = pd.DataFrame({
        "DocumentDate": pd.date_range("2024-01-01", periods=12),
        "RowAmount": list(range(100, 220, 10)),  # strictly increasing
    })
    findings = TrendAnalyzer().analyze(df, pd.DataFrame(), _make_ts_ctx())
    assert len(findings) >= 1
    assert findings[0].extra["mk_trend"] == "increasing"


def test_sens_slope_positive_for_increasing_series():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    df = pd.DataFrame({
        "DocumentDate": pd.date_range("2024-01-01", periods=8),
        "RowAmount": [200, 250, 300, 350, 400, 450, 500, 550],
    })
    findings = TrendAnalyzer().analyze(df, pd.DataFrame(), _make_ts_ctx())
    assert len(findings) >= 1
    assert findings[0].extra["sens_slope"] > 0
