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
