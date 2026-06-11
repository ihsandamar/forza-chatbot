import pandas as pd
import numpy as np


def _make_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="aylık satışlar",
        active_filters=[],
        period_label="son 30 gün",
        dimension_columns=["DocumentDate"],
        metric_columns=["RowAmount"],
    )


def test_weekly_seasonality_detected():
    from src.graphs.report_agent.insight_engine.analyzers.seasonality import SeasonalityAnalyzer
    dates = pd.date_range("2024-01-01", periods=28, freq="D").strftime("%Y-%m-%d").tolist()
    amounts = [5000.0 if i % 7 == 5 else 1000.0 for i in range(28)]
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": amounts})
    findings = SeasonalityAnalyzer().analyze(df, pd.DataFrame(), _make_ctx())
    assert len(findings) >= 1
    seasonal = [f for f in findings if f.type in ("seasonal_peak", "seasonal_trough")]
    assert len(seasonal) >= 1


def test_too_few_rows_skipped():
    from src.graphs.report_agent.insight_engine.analyzers.seasonality import SeasonalityAnalyzer
    df = pd.DataFrame({"DocumentDate": ["2024-01-01", "2024-01-02"], "RowAmount": [100.0, 200.0]})
    assert SeasonalityAnalyzer().analyze(df, pd.DataFrame(), _make_ctx()) == []


def test_no_date_column_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.seasonality import SeasonalityAnalyzer
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    df = pd.DataFrame({"ProductName": ["A"], "RowAmount": [1000.0]})
    ctx = AnalysisContext("q", [], "p", ["ProductName"], ["RowAmount"])
    assert SeasonalityAnalyzer().analyze(df, pd.DataFrame(), ctx) == []


def test_seasonal_peak_has_dow_averages():
    from src.graphs.report_agent.insight_engine.analyzers.seasonality import SeasonalityAnalyzer
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    import numpy as np
    n = 28
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    t_arr = np.arange(n, dtype=float)
    values = 500 + 300 * np.sin(2 * np.pi * t_arr / 7)
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    ctx = AnalysisContext(
        user_query="t", active_filters=[], period_label="test",
        dimension_columns=["DocumentDate"], metric_columns=["RowAmount"],
    )
    findings = SeasonalityAnalyzer().analyze(df, pd.DataFrame(), ctx)
    peaks = [f for f in findings if f.type == "seasonal_peak"]
    assert len(peaks) >= 1
    assert "dow_averages" in peaks[0].extra
    assert "peak_vs_trough_ratio" in peaks[0].extra
    assert len(peaks[0].extra["dow_averages"]) == 7   # all 7 days
    assert peaks[0].extra["peak_vs_trough_ratio"] > 1.0


def test_humanize_seasonal_peak_uses_ratio():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _humanize_evidence
    from src.graphs.report_agent.insight_engine.models import Finding
    f = Finding(
        type="seasonal_peak", analyzer="A", dimension="DayOfWeek", value="Cuma",
        metric="RowAmount", current_value=650000.0, comparison_value=430000.0,
        change_pct=51.2, significance=0.72, period_label="test",
        extra={"autocorr_lag7": 0.8, "fft_period": 7,
               "dow_averages": {"Pazartesi": 430000.0, "Cuma": 650000.0},
               "peak_vs_trough_ratio": 1.51},
    )
    result = _humanize_evidence(f)
    assert "1.51" in result
