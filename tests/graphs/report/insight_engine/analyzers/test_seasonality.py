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
