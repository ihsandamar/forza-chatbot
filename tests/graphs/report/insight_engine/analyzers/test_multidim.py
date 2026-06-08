import pandas as pd


def _make_ctx(dims):
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="haftalık satışlar",
        active_filters=[],
        period_label="bu ay",
        dimension_columns=dims,
        metric_columns=["RowAmount"],
    )


def test_peak_day_detected():
    from src.graphs.report_agent.insight_engine.analyzers.multidim import MultiDimAnalyzer
    df = pd.DataFrame({
        "DayOfWeek": [1, 2, 3, 4, 5, 6, 7],
        "RowAmount": [1000.0, 900.0, 850.0, 800.0, 750.0, 5000.0, 300.0],
    })
    findings = MultiDimAnalyzer().analyze(df, pd.DataFrame(), _make_ctx(["DayOfWeek"]))
    peaks = [f for f in findings if f.type == "peak_period"]
    assert len(peaks) >= 1
    assert peaks[0].value == "6"


def test_weak_period_detected():
    from src.graphs.report_agent.insight_engine.analyzers.multidim import MultiDimAnalyzer
    df = pd.DataFrame({
        "Hour": list(range(8, 22)),
        "RowAmount": [100.0 if h != 14 else 5000.0 for h in range(8, 22)],
    })
    findings = MultiDimAnalyzer().analyze(df, pd.DataFrame(), _make_ctx(["Hour"]))
    weaks = [f for f in findings if f.type == "weak_period"]
    assert len(weaks) >= 1


def test_no_time_column_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.multidim import MultiDimAnalyzer
    df = pd.DataFrame({"ProductName": ["A", "B"], "RowAmount": [1000.0, 2000.0]})
    findings = MultiDimAnalyzer().analyze(df, pd.DataFrame(), _make_ctx(["ProductName"]))
    assert findings == []
