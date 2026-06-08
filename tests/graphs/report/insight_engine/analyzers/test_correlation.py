import pandas as pd
import numpy as np


def _make_ctx(dims, metrics):
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="korelasyon",
        active_filters=[],
        period_label="2024-01",
        dimension_columns=dims,
        metric_columns=metrics,
    )


def test_high_positive_correlation_detected():
    from src.graphs.report_agent.insight_engine.analyzers.correlation import CorrelationAnalyzer
    # Americano ≈ 0.8 × Espresso → r ≈ 1.0
    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    espresso = [100, 120, 80, 90, 110, 100, 90, 105, 115, 85, 95, 110, 100, 95]
    americano = [80,  96, 64, 72,  88,  80, 72,  84,  92, 68, 76,  88,  80, 76]
    rows = (
        [{"DocumentDate": d, "ProductName": "Espresso", "RowAmount": v} for d, v in zip(dates, espresso)] +
        [{"DocumentDate": d, "ProductName": "Americano", "RowAmount": v} for d, v in zip(dates, americano)]
    )
    df = pd.DataFrame(rows)
    ctx = _make_ctx(dims=["DocumentDate", "ProductName"], metrics=["RowAmount"])
    findings = CorrelationAnalyzer().analyze(df, pd.DataFrame(), ctx)
    positives = [f for f in findings if f.type == "high_positive_correlation"]
    assert len(positives) >= 1
    assert positives[0].extra["r"] > 0.75


def test_high_negative_correlation_detected():
    from src.graphs.report_agent.insight_engine.analyzers.correlation import CorrelationAnalyzer
    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    a_vals = [100, 120, 80, 90, 110, 100, 90, 105, 115, 85, 95, 110, 100, 95]
    b_vals = [80,  60, 100, 90, 70,  80,  90, 75,   65, 95, 85,  70,  80, 85]
    rows = (
        [{"DocumentDate": d, "ProductName": "A", "RowAmount": v} for d, v in zip(dates, a_vals)] +
        [{"DocumentDate": d, "ProductName": "B", "RowAmount": v} for d, v in zip(dates, b_vals)]
    )
    df = pd.DataFrame(rows)
    ctx = _make_ctx(dims=["DocumentDate", "ProductName"], metrics=["RowAmount"])
    findings = CorrelationAnalyzer().analyze(df, pd.DataFrame(), ctx)
    negatives = [f for f in findings if f.type == "high_negative_correlation"]
    assert len(negatives) >= 1
    assert negatives[0].extra["r"] < -0.75


def test_no_date_column_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.correlation import CorrelationAnalyzer
    df = pd.DataFrame({"ProductName": ["A", "B"], "RowAmount": [100.0, 200.0]})
    ctx = _make_ctx(dims=["ProductName"], metrics=["RowAmount"])
    findings = CorrelationAnalyzer().analyze(df, pd.DataFrame(), ctx)
    assert findings == []


def test_single_product_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.correlation import CorrelationAnalyzer
    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    rows = [{"DocumentDate": d, "ProductName": "OnlyProduct", "RowAmount": 100.0} for d in dates]
    df = pd.DataFrame(rows)
    ctx = _make_ctx(dims=["DocumentDate", "ProductName"], metrics=["RowAmount"])
    findings = CorrelationAnalyzer().analyze(df, pd.DataFrame(), ctx)
    assert findings == []
