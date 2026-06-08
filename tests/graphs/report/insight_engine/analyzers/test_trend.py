# tests/graphs/report/insight_engine/analyzers/test_trend.py
import pandas as pd


def _make_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="satışlar",
        active_filters=[],
        period_label="son 7 gün vs önceki 7 gün",
        dimension_columns=["ProductName"],
        metric_columns=["RowAmount"],
    )


def test_base_analyzer_interface():
    from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
    import inspect
    assert inspect.isabstract(BaseAnalyzer)
    assert hasattr(BaseAnalyzer, "analyze")
    assert hasattr(BaseAnalyzer, "name")
