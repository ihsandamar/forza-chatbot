# tests/graphs/report/insight_engine/analyzers/test_segment_bcg.py
import pandas as pd


def _make_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="bcg analizi",
        active_filters=[],
        period_label="2024-01",
        dimension_columns=["ProductName"],
        metric_columns=["RowAmount"],
    )


def test_bcg_star_detected():
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    current = pd.DataFrame({
        "ProductName": ["Star", "Dog", "CashCow", "Question"],
        "RowAmount": [5000.0, 200.0, 3000.0, 100.0],
    })
    comparison = pd.DataFrame({
        "ProductName": ["Star", "Dog", "CashCow", "Question"],
        "RowAmount": [2000.0, 250.0, 2900.0, 50.0],
    })
    findings = SegmentComparator().analyze(current, comparison, _make_ctx())
    bcg_types = [f.type for f in findings]
    assert "bcg_star" in bcg_types
    star = next(f for f in findings if f.type == "bcg_star")
    assert star.value == "Star"
    assert "growth_pct" in star.extra


def test_bcg_dog_detected():
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    current = pd.DataFrame({
        "ProductName": ["Star", "Dog", "CashCow", "Question"],
        "RowAmount": [5000.0, 200.0, 3000.0, 800.0],
    })
    comparison = pd.DataFrame({
        "ProductName": ["Star", "Dog", "CashCow", "Question"],
        "RowAmount": [2000.0, 280.0, 2800.0, 400.0],
    })
    findings = SegmentComparator().analyze(current, comparison, _make_ctx())
    bcg_types = [f.type for f in findings]
    assert "bcg_dog" in bcg_types


def test_bcg_skipped_when_no_comparison():
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    current = pd.DataFrame({
        "ProductName": ["A", "B", "C", "D"],
        "RowAmount": [100.0, 200.0, 300.0, 400.0],
    })
    findings = SegmentComparator().analyze(current, pd.DataFrame(), _make_ctx())
    assert not any("bcg_" in f.type for f in findings)


def test_bcg_skipped_when_fewer_than_4_segments():
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    current = pd.DataFrame({"ProductName": ["A", "B"], "RowAmount": [100.0, 200.0]})
    comparison = pd.DataFrame({"ProductName": ["A", "B"], "RowAmount": [80.0, 150.0]})
    findings = SegmentComparator().analyze(current, comparison, _make_ctx())
    assert not any("bcg_" in f.type for f in findings)
