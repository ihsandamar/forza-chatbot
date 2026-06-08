import pandas as pd
import numpy as np


def _make_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="mevsimsellik",
        active_filters=[],
        period_label="2024-01",
        dimension_columns=["DocumentDate"],
        metric_columns=["RowAmount"],
    )


def test_fft_detects_14_day_period():
    from src.graphs.report_agent.insight_engine.analyzers.seasonality import SeasonalityAnalyzer
    n = 56
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    t = np.arange(n, dtype=float)
    values = 500 + 200 * np.sin(2 * np.pi * t / 14)
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    findings = SeasonalityAnalyzer().analyze(df, pd.DataFrame(), _make_ctx())
    periodic = [f for f in findings if f.type == "periodic_pattern"]
    assert len(periodic) >= 1
    assert periodic[0].extra["fft_period"] in range(12, 17)


def test_fft_no_false_positive_on_noise():
    from src.graphs.report_agent.insight_engine.analyzers.seasonality import SeasonalityAnalyzer
    rng = np.random.default_rng(42)
    n = 28
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    values = rng.uniform(90, 110, n)
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    findings = SeasonalityAnalyzer().analyze(df, pd.DataFrame(), _make_ctx())
    periodic = [f for f in findings if f.type == "periodic_pattern"]
    assert len(periodic) == 0


def test_fft_period_added_to_seasonal_peak_extra():
    from src.graphs.report_agent.insight_engine.analyzers.seasonality import SeasonalityAnalyzer
    n = 28
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    t = np.arange(n, dtype=float)
    values = 500 + 300 * np.sin(2 * np.pi * t / 7)
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    findings = SeasonalityAnalyzer().analyze(df, pd.DataFrame(), _make_ctx())
    seasonal_peaks = [f for f in findings if f.type == "seasonal_peak"]
    assert len(seasonal_peaks) >= 1, "Expected seasonal_peak finding for strong 7-day signal"
    assert "fft_period" in seasonal_peaks[0].extra
