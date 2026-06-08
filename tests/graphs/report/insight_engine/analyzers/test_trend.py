# tests/graphs/report/insight_engine/analyzers/test_trend.py
import pandas as pd


def _make_ctx(dims=None, metrics=None):
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="satışlar",
        active_filters=[],
        period_label="son 7 gün vs önceki 7 gün",
        dimension_columns=dims or ["ProductName"],
        metric_columns=metrics or ["RowAmount"],
    )


def test_base_analyzer_interface():
    from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
    import inspect
    assert inspect.isabstract(BaseAnalyzer)
    assert hasattr(BaseAnalyzer, "analyze")
    assert hasattr(BaseAnalyzer, "name")


def test_trend_decline_detected():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    current = pd.DataFrame({"ProductName": ["Burger", "Pizza"], "RowAmount": [1250.0, 2000.0]})
    comparison = pd.DataFrame({"ProductName": ["Burger", "Pizza"], "RowAmount": [1850.0, 1900.0]})
    findings = TrendAnalyzer().analyze(current, comparison, _make_ctx())
    declines = [f for f in findings if f.type == "trend_decline" and f.value == "Burger"]
    assert len(declines) == 1
    assert declines[0].change_pct < 0
    assert declines[0].significance > 0


def test_trend_increase_detected():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    current = pd.DataFrame({"ProductName": ["Burger"], "RowAmount": [2500.0]})
    comparison = pd.DataFrame({"ProductName": ["Burger"], "RowAmount": [1000.0]})
    findings = TrendAnalyzer().analyze(current, comparison, _make_ctx())
    increases = [f for f in findings if f.type == "trend_increase"]
    assert len(increases) == 1
    assert increases[0].change_pct > 0


def test_small_change_ignored():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    current = pd.DataFrame({"ProductName": ["Burger"], "RowAmount": [1020.0]})
    comparison = pd.DataFrame({"ProductName": ["Burger"], "RowAmount": [1000.0]})
    findings = TrendAnalyzer().analyze(current, comparison, _make_ctx())
    assert len(findings) == 0  # 2% change — below threshold


def test_empty_comparison_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    current = pd.DataFrame({"ProductName": ["Burger"], "RowAmount": [1000.0]})
    findings = TrendAnalyzer().analyze(current, pd.DataFrame(), _make_ctx())
    assert findings == []


def test_time_series_slope():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    current = pd.DataFrame({
        "DocumentDate": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
        "RowAmount": [1000.0, 800.0, 600.0, 400.0, 200.0],
    })
    ctx = _make_ctx(dims=["DocumentDate"], metrics=["RowAmount"])
    findings = TrendAnalyzer().analyze(current, pd.DataFrame(), ctx)
    time_findings = [f for f in findings if f.type == "trend_decline"]
    assert len(time_findings) >= 1
    assert time_findings[0].extra.get("slope") is not None


def test_non_date_single_dimension_does_not_trigger_timeseries():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    # ProductName is not a date column — should NOT trigger time-series path
    # Without comparison_df, segment path also returns []
    current = pd.DataFrame({
        "ProductName": ["Burger", "Pizza", "Salad", "Wrap", "Soup"],
        "RowAmount": [1000.0, 800.0, 600.0, 400.0, 200.0],
    })
    ctx = _make_ctx(dims=["ProductName"], metrics=["RowAmount"])
    findings = TrendAnalyzer().analyze(current, pd.DataFrame(), ctx)
    # Should be empty — no comparison, ProductName is not a date column
    assert findings == []
