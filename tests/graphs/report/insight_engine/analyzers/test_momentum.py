import pandas as pd
import numpy as np


def _make_ctx(**kwargs):
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    defaults = dict(
        user_query="momentum analizi",
        active_filters=[],
        period_label="2024-01-01 – 2024-01-14",
        dimension_columns=["DocumentDate"],
        metric_columns=["RowAmount"],
    )
    return AnalysisContext(**{**defaults, **kwargs})


def test_wow_surge_detected():
    from src.graphs.report_agent.insight_engine.analyzers.momentum import MomentumAnalyzer
    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    values = [100.0] * 7 + [300.0] * 7  # last week 3× previous week
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    findings = MomentumAnalyzer().analyze(df, pd.DataFrame(), _make_ctx())
    assert any(f.type == "wow_surge" for f in findings)
    surge = next(f for f in findings if f.type == "wow_surge")
    assert surge.change_pct > 20.0


def test_wow_drop_detected():
    from src.graphs.report_agent.insight_engine.analyzers.momentum import MomentumAnalyzer
    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    values = [300.0] * 7 + [100.0] * 7  # last week 67% below previous
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    findings = MomentumAnalyzer().analyze(df, pd.DataFrame(), _make_ctx())
    assert any(f.type == "wow_drop" for f in findings)


def test_high_volatility_detected():
    from src.graphs.report_agent.insight_engine.analyzers.momentum import MomentumAnalyzer
    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    values = [100.0, 1000.0] * 7
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    findings = MomentumAnalyzer().analyze(df, pd.DataFrame(), _make_ctx())
    assert any(f.type == "high_volatility" for f in findings)
    vol = next(f for f in findings if f.type == "high_volatility")
    assert vol.extra["cv"] > 0.5


def test_high_momentum_detected():
    from src.graphs.report_agent.insight_engine.analyzers.momentum import MomentumAnalyzer
    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    values = list(np.linspace(100, 800, 14))  # strong upward, tight fit
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    findings = MomentumAnalyzer().analyze(df, pd.DataFrame(), _make_ctx())
    assert any(f.type == "high_momentum" for f in findings)
    m = next(f for f in findings if f.type == "high_momentum")
    assert m.extra["r_squared"] > 0.9


def test_no_date_column_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.momentum import MomentumAnalyzer
    df = pd.DataFrame({"ProductName": ["A", "B"], "RowAmount": [100.0, 200.0]})
    ctx = _make_ctx(dimension_columns=["ProductName"])
    findings = MomentumAnalyzer().analyze(df, pd.DataFrame(), ctx)
    assert findings == []


def test_too_few_rows_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.momentum import MomentumAnalyzer
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": [100.0] * 5})
    findings = MomentumAnalyzer().analyze(df, pd.DataFrame(), _make_ctx())
    assert findings == []
