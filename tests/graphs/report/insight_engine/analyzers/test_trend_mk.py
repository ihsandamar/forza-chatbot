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


def test_time_series_extra_has_date_range():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    df = pd.DataFrame({
        "DocumentDate": pd.date_range("2024-01-01", periods=10),
        "RowAmount": [100, 110, 120, 130, 140, 150, 160, 170, 180, 190],
    })
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    ctx = AnalysisContext(user_query="t", active_filters=[], period_label="test",
                          dimension_columns=["DocumentDate"], metric_columns=["RowAmount"])
    findings = TrendAnalyzer().analyze(df, pd.DataFrame(), ctx)
    assert len(findings) == 1
    extra = findings[0].extra
    assert "start_date" in extra
    assert "end_date" in extra
    assert "n_points" in extra
    assert extra["start_date"] == "2024-01-01"
    assert extra["end_date"] == "2024-01-10"
    assert extra["n_points"] == 10


def test_humanize_trend_uses_dates():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _humanize_evidence
    from src.graphs.report_agent.insight_engine.models import Finding
    f = Finding(
        type="trend_decline", analyzer="A", dimension="DocumentDate", value="zaman serisi",
        metric="RowAmount", current_value=200.0, comparison_value=993.0,
        change_pct=-32.5, significance=0.91, period_label="test",
        extra={"slope": -10.2, "r_squared": 0.84,
               "start_date": "2024-01-01", "end_date": "2024-03-23", "n_points": 82},
    )
    result = _humanize_evidence(f)
    assert "2024-01-01" in result
    assert "2024-03-23" in result
    assert "82" in result
