import pandas as pd


def _make_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="kategori satışları",
        active_filters=[],
        period_label="bu ay",
        dimension_columns=["CategoryName"],
        metric_columns=["RowAmount"],
    )


def test_top_performer_detected():
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    df = pd.DataFrame({
        "CategoryName": ["İçecek", "Yiyecek", "Tatlı", "Atıştırmalık"],
        "RowAmount": [5000.0, 1000.0, 800.0, 700.0],
    })
    findings = SegmentComparator().analyze(df, pd.DataFrame(), _make_ctx())
    tops = [f for f in findings if f.type == "top_performer" and f.value == "İçecek"]
    assert len(tops) == 1
    assert tops[0].significance > 0


def test_bottom_performer_detected():
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    df = pd.DataFrame({
        "CategoryName": ["A", "B", "C", "D"],
        "RowAmount": [5000.0, 4800.0, 4900.0, 100.0],
    })
    findings = SegmentComparator().analyze(df, pd.DataFrame(), _make_ctx())
    bottoms = [f for f in findings if f.type == "bottom_performer" and f.value == "D"]
    assert len(bottoms) == 1


def test_pareto_dominant_detected():
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    df = pd.DataFrame({
        "CategoryName": ["A", "B", "C", "D", "E"],
        "RowAmount": [8000.0, 1000.0, 500.0, 300.0, 200.0],
    })
    findings = SegmentComparator().analyze(df, pd.DataFrame(), _make_ctx())
    pareto = [f for f in findings if f.type == "pareto_dominant"]
    assert len(pareto) >= 1


def test_single_row_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    df = pd.DataFrame({"CategoryName": ["A"], "RowAmount": [5000.0]})
    assert SegmentComparator().analyze(df, pd.DataFrame(), _make_ctx()) == []
