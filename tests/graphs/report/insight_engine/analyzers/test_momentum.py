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


def test_accelerating_detected():
    from src.graphs.report_agent.insight_engine.analyzers.momentum import MomentumAnalyzer
    # Second half grows 3× faster than first half
    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    # First 7: slope ~10/step. Second 7: slope ~50/step
    first_half = [100, 110, 120, 130, 140, 150, 160]
    second_half = [160, 210, 260, 310, 360, 410, 460]
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": first_half + second_half})
    findings = MomentumAnalyzer().analyze(df, pd.DataFrame(), _make_ctx())
    types = [f.type for f in findings]
    assert "accelerating" in types


def test_decelerating_detected():
    from src.graphs.report_agent.insight_engine.analyzers.momentum import MomentumAnalyzer
    # First half: strong growth. Second half: flat/declining
    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    first_half = [100, 200, 300, 400, 500, 600, 700]
    second_half = [710, 720, 715, 718, 712, 710, 708]  # nearly flat after strong rise
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": first_half + second_half})
    findings = MomentumAnalyzer().analyze(df, pd.DataFrame(), _make_ctx())
    types = [f.type for f in findings]
    assert "decelerating" in types


def test_wow_surge_has_date_range():
    from src.graphs.report_agent.insight_engine.analyzers.momentum import MomentumAnalyzer
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    dates = pd.date_range("2024-03-10", periods=14, freq="D")
    values = [100.0] * 7 + [300.0] * 7
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    ctx = AnalysisContext(user_query="t", active_filters=[], period_label="test",
                          dimension_columns=["DocumentDate"], metric_columns=["RowAmount"])
    findings = MomentumAnalyzer().analyze(df, pd.DataFrame(), ctx)
    surge = next(f for f in findings if f.type == "wow_surge")
    assert "last7_start" in surge.extra
    assert "last7_end" in surge.extra
    assert "prev7_start" in surge.extra
    assert "prev7_end" in surge.extra
    assert surge.extra["last7_start"] == "2024-03-17"
    assert surge.extra["last7_end"] == "2024-03-23"
    assert surge.extra["prev7_start"] == "2024-03-10"
    assert surge.extra["prev7_end"] == "2024-03-16"


def test_high_momentum_has_period_dates():
    from src.graphs.report_agent.insight_engine.analyzers.momentum import MomentumAnalyzer
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    import numpy as np
    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    values = list(np.linspace(100, 800, 14))
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    ctx = AnalysisContext(user_query="t", active_filters=[], period_label="test",
                          dimension_columns=["DocumentDate"], metric_columns=["RowAmount"])
    findings = MomentumAnalyzer().analyze(df, pd.DataFrame(), ctx)
    momentum = next((f for f in findings if f.type == "high_momentum"), None)
    assert momentum is not None
    assert "period_start" in momentum.extra
    assert "period_end" in momentum.extra
    assert momentum.extra["period_start"] == "2024-01-01"
    assert momentum.extra["period_end"] == "2024-01-14"


def test_humanize_wow_uses_dates():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _humanize_evidence
    from src.graphs.report_agent.insight_engine.models import Finding
    f = Finding(
        type="wow_surge", analyzer="A", dimension="DocumentDate", value="son 7 gün",
        metric="RowAmount", current_value=1200000.0, comparison_value=480000.0,
        change_pct=150.0, significance=0.8, period_label="test",
        extra={"last7_sum": 1200000.0, "prev7_sum": 480000.0,
               "last7_start": "2024-03-17", "last7_end": "2024-03-23",
               "prev7_start": "2024-03-10", "prev7_end": "2024-03-16"},
    )
    result = _humanize_evidence(f)
    # Should contain the date ranges
    assert "2024-03-17" in result or "03-17" in result
    assert "2024-03-10" in result or "03-10" in result
