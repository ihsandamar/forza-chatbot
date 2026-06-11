# tests/graphs/report/insight_engine/analyzers/test_anomaly.py
import pandas as pd


def _make_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="şube performansı",
        active_filters=[],
        period_label="bu ay",
        dimension_columns=["BranchName"],
        metric_columns=["RowAmount"],
    )


def test_outlier_low_detected():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    df = pd.DataFrame({
        "BranchName": ["Ankara", "İstanbul", "İzmir", "Bursa", "Antalya"],
        "RowAmount": [1000.0, 9000.0, 8500.0, 9200.0, 8800.0],
    })
    findings = AnomalyDetector().analyze(df, pd.DataFrame(), _make_ctx())
    lows = [f for f in findings if f.type == "anomaly_low" and f.value == "Ankara"]
    assert len(lows) == 1
    assert lows[0].extra.get("z_score") is not None
    assert lows[0].extra["z_score"] < 0


def test_outlier_high_detected():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    df = pd.DataFrame({
        "BranchName": ["Ankara", "İstanbul", "İzmir", "Bursa", "Antalya"],
        "RowAmount": [15000.0, 1000.0, 1200.0, 900.0, 1100.0],
    })
    findings = AnomalyDetector().analyze(df, pd.DataFrame(), _make_ctx())
    highs = [f for f in findings if f.type == "anomaly_high" and f.value == "Ankara"]
    assert len(highs) == 1


def test_no_anomaly_when_homogeneous():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    df = pd.DataFrame({
        "BranchName": ["A", "B", "C", "D"],
        "RowAmount": [1000.0, 1010.0, 990.0, 1005.0],
    })
    findings = AnomalyDetector().analyze(df, pd.DataFrame(), _make_ctx())
    assert len(findings) == 0


def test_too_few_rows_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    df = pd.DataFrame({"BranchName": ["Ankara"], "RowAmount": [1000.0]})
    assert AnomalyDetector().analyze(df, pd.DataFrame(), _make_ctx()) == []


def test_anomaly_high_has_date_when_date_col_in_df():
    """date×product matrix: each row has date → anomaly_date should be in extra."""
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    import pandas as pd
    ctx = AnalysisContext(
        user_query="t", active_filters=[], period_label="test",
        dimension_columns=["ProductName", "DocumentDate"],
        metric_columns=["RowAmount"],
    )
    rows = [
        {"ProductName": "ESPRESSO", "DocumentDate": "2024-02-14", "RowAmount": 480000.0},
        {"ProductName": "LATTE",    "DocumentDate": "2024-02-14", "RowAmount": 84000.0},
        {"ProductName": "MOCHA",    "DocumentDate": "2024-02-14", "RowAmount": 90000.0},
        {"ProductName": "AMERICANO","DocumentDate": "2024-02-14", "RowAmount": 80000.0},
    ]
    df = pd.DataFrame(rows)
    findings = AnomalyDetector().analyze(df, pd.DataFrame(), ctx)
    anomalies = [f for f in findings if f.type == "anomaly_high"]
    assert len(anomalies) >= 1
    espresso = next((f for f in anomalies if f.value == "ESPRESSO"), None)
    assert espresso is not None
    assert "anomaly_date" in espresso.extra
    assert espresso.extra["anomaly_date"] == "2024-02-14"
