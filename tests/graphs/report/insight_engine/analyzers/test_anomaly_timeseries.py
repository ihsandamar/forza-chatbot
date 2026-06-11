# tests/graphs/report/insight_engine/analyzers/test_anomaly_timeseries.py
import pandas as pd
import numpy as np


def _make_ctx(dims=None, metrics=None):
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="anomali",
        active_filters=[],
        period_label="2024-01",
        dimension_columns=dims or ["DocumentDate"],
        metric_columns=metrics or ["RowAmount"],
    )


def test_cusum_shift_detected_on_step_change():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    n = 20
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    values = [100.0] * 10 + [300.0] * 10
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    findings = AnomalyDetector().analyze(df, pd.DataFrame(), _make_ctx())
    types = [f.type for f in findings]
    assert "cusum_shift" in types
    shift = next(f for f in findings if f.type == "cusum_shift")
    assert shift.extra["direction"] == "up"
    assert "shift_date" in shift.extra


def test_regime_change_detected():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    n = 20
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    values = [500.0] * 10 + [100.0] * 10
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    findings = AnomalyDetector().analyze(df, pd.DataFrame(), _make_ctx())
    types = [f.type for f in findings]
    assert "regime_change" in types
    cp = next(f for f in findings if f.type == "regime_change")
    assert "changepoint_date" in cp.extra


def test_no_shift_when_stable():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    dates = pd.date_range("2024-01-01", periods=20, freq="D")
    stable_values = [100, 102, 99, 101, 100, 103, 98, 101, 100, 102,
                     99, 101, 100, 103, 98, 101, 100, 102, 99, 101]
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": [float(v) for v in stable_values]})
    findings = AnomalyDetector().analyze(df, pd.DataFrame(), _make_ctx())
    shift_types = [f.type for f in findings if f.type in ("cusum_shift", "regime_change")]
    assert len(shift_types) == 0


def test_time_shift_ignored_when_no_date_column():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    values = [100.0, 200.0, 50.0, 300.0, 80.0, 400.0, 60.0]
    df = pd.DataFrame({"ProductName": list("ABCDEFG"), "RowAmount": values})
    ctx = _make_ctx(dims=["ProductName"])
    findings = AnomalyDetector().analyze(df, pd.DataFrame(), ctx)
    shift_types = [f.type for f in findings if f.type in ("cusum_shift", "regime_change")]
    assert len(shift_types) == 0


def test_cusum_shift_has_n_before_n_after():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    import pandas as pd
    ctx = AnalysisContext(
        user_query="t", active_filters=[], period_label="test",
        dimension_columns=["DocumentDate"], metric_columns=["RowAmount"],
    )
    n = 20
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    values = [100.0] * 10 + [300.0] * 10
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    findings = AnomalyDetector().analyze(df, pd.DataFrame(), ctx)
    cusum = next((f for f in findings if f.type == "cusum_shift"), None)
    assert cusum is not None
    assert "n_before" in cusum.extra
    assert "n_after" in cusum.extra
    assert "analysis_start" in cusum.extra
    assert "analysis_end" in cusum.extra
    assert cusum.extra["analysis_start"] == "2024-01-01"
    assert cusum.extra["analysis_end"] == "2024-01-20"
    assert cusum.extra["n_before"] + cusum.extra["n_after"] == n
