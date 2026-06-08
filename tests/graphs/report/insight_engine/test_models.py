def test_finding_defaults():
    from src.graphs.report_agent.insight_engine.models import Finding
    f = Finding(
        type="trend_decline",
        analyzer="TrendAnalyzer",
        dimension="ProductName",
        value="Burger",
        metric="RowAmount",
        current_value=1250.0,
        comparison_value=1850.0,
        change_pct=-32.5,
        significance=0.91,
        period_label="son 7 gün vs önceki 7 gün",
    )
    assert f.extra == {}
    assert f.significance == 0.91


def test_analysis_context():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    ctx = AnalysisContext(
        user_query="satışlar",
        active_filters=[{"field": "BranchName", "value": "Ankara"}],
        period_label="Ocak 2024",
        dimension_columns=["ProductName"],
        metric_columns=["RowAmount"],
    )
    assert ctx.dimension_columns == ["ProductName"]


def test_finding_to_dict():
    from src.graphs.report_agent.insight_engine.models import Finding
    f = Finding(
        type="anomaly_high",
        analyzer="AnomalyDetector",
        dimension="BranchName",
        value="Ankara",
        metric="RowAmount",
        current_value=9500.0,
        comparison_value=5000.0,
        change_pct=90.0,
        significance=0.85,
        period_label="bu ay",
        extra={"z_score": 2.8},
    )
    d = f.to_dict()
    assert d["type"] == "anomaly_high"
    assert d["extra"]["z_score"] == 2.8
