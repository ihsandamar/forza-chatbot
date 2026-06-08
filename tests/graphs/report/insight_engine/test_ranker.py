from src.graphs.report_agent.insight_engine.models import Finding


def _make_finding(sig: float, type_: str = "trend_decline") -> Finding:
    return Finding(
        type=type_, analyzer="A", dimension="D", value="V",
        metric="M", current_value=1.0, comparison_value=2.0,
        change_pct=-50.0, significance=sig, period_label="p",
    )


def test_ranker_sorts_by_significance():
    from src.graphs.report_agent.insight_engine.ranker import FindingsRanker
    findings = [_make_finding(0.3), _make_finding(0.9), _make_finding(0.6)]
    ranked = FindingsRanker().rank(findings)
    sigs = [f.significance for f in ranked]
    assert sigs == sorted(sigs, reverse=True)


def test_ranker_filters_below_threshold():
    from src.graphs.report_agent.insight_engine.ranker import FindingsRanker
    findings = [_make_finding(0.1), _make_finding(0.2), _make_finding(0.9)]
    ranked = FindingsRanker().rank(findings)
    assert all(f.significance >= 0.15 for f in ranked)
    assert len(ranked) == 2  # 0.1 filtered, 0.2 and 0.9 pass


def test_ranker_caps_at_top_n():
    from src.graphs.report_agent.insight_engine.ranker import FindingsRanker, TOP_N
    findings = [_make_finding(float(i) / 10) for i in range(5, 15)]
    ranked = FindingsRanker().rank(findings)
    assert len(ranked) <= TOP_N


def test_ranker_empty_input():
    from src.graphs.report_agent.insight_engine.ranker import FindingsRanker
    assert FindingsRanker().rank([]) == []


def test_diversity_filter_caps_per_type():
    from src.graphs.report_agent.insight_engine.ranker import FindingsRanker
    from src.graphs.report_agent.insight_engine.models import Finding
    # 5 adet "trend_decline" — max 3 geçmeli
    findings = [
        Finding(
            type="trend_decline",
            analyzer="TrendAnalyzer",
            dimension="ProductName",
            value=f"P{i}",
            metric="RowAmount",
            current_value=float(i * 100),
            comparison_value=float(i * 200),
            change_pct=-30.0,
            significance=0.5 + i * 0.05,
            period_label="test",
        )
        for i in range(5)
    ]
    ranked = FindingsRanker().rank(findings)
    trend_declines = [f for f in ranked if f.type == "trend_decline"]
    assert len(trend_declines) <= 3


def test_top_n_is_12():
    from src.graphs.report_agent.insight_engine.ranker import TOP_N
    assert TOP_N == 12


def test_diversity_preserves_different_types():
    from src.graphs.report_agent.insight_engine.ranker import FindingsRanker
    from src.graphs.report_agent.insight_engine.models import Finding

    def make(type_, sig):
        return Finding(
            type=type_, analyzer="X", dimension="D", value="V", metric="M",
            current_value=1.0, comparison_value=0.0, change_pct=10.0,
            significance=sig, period_label="test",
        )

    findings = [make("trend_decline", 0.9), make("anomaly_high", 0.85), make("bcg_star", 0.8)]
    ranked = FindingsRanker().rank(findings)
    types = {f.type for f in ranked}
    assert "trend_decline" in types
    assert "anomaly_high" in types
    assert "bcg_star" in types
