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
