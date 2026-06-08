import pandas as pd


def _make_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="satışlar",
        active_filters=[],
        period_label="bu ay",
        dimension_columns=["ProductName"],
        metric_columns=["RowAmount"],
    )


def test_engine_runs_all_analyzers():
    from src.graphs.report_agent.insight_engine.engine import MathEngine
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector

    current = pd.DataFrame({
        "ProductName": ["A", "B", "C", "D", "E"],
        "RowAmount": [5000.0, 1000.0, 900.0, 950.0, 920.0],
    })
    comparison = pd.DataFrame({
        "ProductName": ["A", "B", "C", "D", "E"],
        "RowAmount": [2000.0, 1000.0, 900.0, 950.0, 920.0],
    })
    engine = MathEngine(analyzers=[TrendAnalyzer(), AnomalyDetector()])
    findings = engine.run(current, comparison, _make_ctx())
    assert len(findings) >= 1


def test_engine_skips_failing_analyzer():
    from src.graphs.report_agent.insight_engine.engine import MathEngine
    from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
    from src.graphs.report_agent.insight_engine.models import Finding

    class BrokenAnalyzer(BaseAnalyzer):
        @property
        def name(self):
            return "BrokenAnalyzer"
        def analyze(self, current_df, comparison_df, context):
            raise RuntimeError("broken")

    class GoodAnalyzer(BaseAnalyzer):
        @property
        def name(self):
            return "GoodAnalyzer"
        def analyze(self, current_df, comparison_df, context):
            return [Finding("t", "GoodAnalyzer", "d", "v", "m", 1.0, 0.0, 100.0, 0.9, "p")]

    engine = MathEngine(analyzers=[BrokenAnalyzer(), GoodAnalyzer()])
    findings = engine.run(pd.DataFrame(), pd.DataFrame(), _make_ctx())
    assert len(findings) == 1
    assert findings[0].analyzer == "GoodAnalyzer"


def test_engine_empty_df_returns_empty():
    from src.graphs.report_agent.insight_engine.engine import MathEngine
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    engine = MathEngine(analyzers=[TrendAnalyzer()])
    findings = engine.run(pd.DataFrame(), pd.DataFrame(), _make_ctx())
    assert findings == []


def test_default_engine_includes_momentum_and_correlation():
    from src.graphs.report_agent.insight_engine.engine import build_default_engine
    from src.graphs.report_agent.insight_engine.analyzers.momentum import MomentumAnalyzer
    from src.graphs.report_agent.insight_engine.analyzers.correlation import CorrelationAnalyzer
    engine = build_default_engine()
    names = [a.name for a in engine.analyzers]
    assert "MomentumAnalyzer" in names
    assert "CorrelationAnalyzer" in names


def test_engine_produces_momentum_finding_for_trending_data():
    import numpy as np
    from src.graphs.report_agent.insight_engine.engine import build_default_engine
    from src.graphs.report_agent.insight_engine.models import AnalysisContext

    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    values = list(np.linspace(100, 600, 14))
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": values})
    ctx = AnalysisContext(
        user_query="trend",
        active_filters=[],
        period_label="2024-01",
        dimension_columns=["DocumentDate"],
        metric_columns=["RowAmount"],
    )
    engine = build_default_engine()
    findings = engine.run(df, pd.DataFrame(), ctx)
    types = {f.type for f in findings}
    assert "high_momentum" in types or "trend_increase" in types


def test_engine_produces_correlation_for_two_product_date_data():
    from src.graphs.report_agent.insight_engine.engine import build_default_engine
    from src.graphs.report_agent.insight_engine.models import AnalysisContext

    dates = pd.date_range("2024-01-01", periods=14, freq="D")
    espresso = [100, 120, 80, 90, 110, 100, 90, 105, 115, 85, 95, 110, 100, 95]
    americano = [80,  96, 64, 72,  88,  80, 72,  84,  92, 68, 76,  88,  80, 76]
    rows = (
        [{"DocumentDate": d, "ProductName": "Espresso", "RowAmount": v} for d, v in zip(dates, espresso)] +
        [{"DocumentDate": d, "ProductName": "Americano", "RowAmount": v} for d, v in zip(dates, americano)]
    )
    df = pd.DataFrame(rows)
    ctx = AnalysisContext(
        user_query="korelasyon",
        active_filters=[],
        period_label="2024-01",
        dimension_columns=["DocumentDate", "ProductName"],
        metric_columns=["RowAmount"],
    )
    engine = build_default_engine()
    findings = engine.run(df, pd.DataFrame(), ctx)
    assert any(f.type == "high_positive_correlation" for f in findings)
