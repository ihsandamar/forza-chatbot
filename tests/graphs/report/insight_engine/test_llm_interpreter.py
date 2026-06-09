"""
Tests for LLMInterpreter — findings JSON → natural language + action recommendations.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.graphs.report_agent.insight_engine.models import Finding, AnalysisContext


def _make_finding(type_="trend_decline", value="Burger", sig=0.9) -> Finding:
    return Finding(
        type=type_, analyzer="TrendAnalyzer", dimension="ProductName",
        value=value, metric="RowAmount", current_value=1250.0,
        comparison_value=1850.0, change_pct=-32.5, significance=sig,
        period_label="son 7 gün vs önceki 7 gün",
    )


def test_build_prompt_contains_findings():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    ctx = AnalysisContext("nelere dikkat etmeliyim", [], "bu ay", ["ProductName"], ["RowAmount"])
    findings = [_make_finding()]
    llm_mock = MagicMock()
    interpreter = LLMInterpreter(llm_mock)
    prompt = interpreter._build_prompt(findings, ctx)
    assert "trend_decline" in prompt
    assert "Burger" in prompt
    assert "-32.5" in prompt
    assert "hesaplama yapma" in prompt.lower() or "kendi hesaplama" in prompt.lower()


def test_build_prompt_no_findings():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    ctx = AnalysisContext("nelere dikkat", [], "bu ay", ["ProductName"], ["RowAmount"])
    llm_mock = MagicMock()
    interpreter = LLMInterpreter(llm_mock)
    prompt = interpreter._build_prompt([], ctx)
    assert "bulgu" in prompt.lower() or "bulunamadı" in prompt.lower()


def test_interpret_returns_string():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    ctx = AnalysisContext("insight ver", [], "bu ay", ["ProductName"], ["RowAmount"])
    findings = [_make_finding()]
    llm_mock = MagicMock()
    llm_mock.ainvoke = AsyncMock(return_value=MagicMock(content="Burger satışları düştü. Kampanya öneririm."))
    interpreter = LLMInterpreter(llm_mock)
    result = asyncio.run(interpreter.interpret(findings, ctx))
    assert isinstance(result, str)
    assert len(result) > 0


def _make_ctx_for_prompt():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="neler önemli?",
        active_filters=[],
        period_label="2024-01-01 – 2024-01-31",
        dimension_columns=["ProductName"],
        metric_columns=["RowAmount"],
    )


def _make_finding2(ftype, value="TestProduct", sig=0.7, extra=None):
    from src.graphs.report_agent.insight_engine.models import Finding
    return Finding(
        type=ftype,
        analyzer="TestAnalyzer",
        dimension="ProductName",
        value=value,
        metric="RowAmount",
        current_value=100.0,
        comparison_value=80.0,
        change_pct=25.0,
        significance=sig,
        period_label="2024-01-01 – 2024-01-31",
        extra=extra or {},
    )


def test_grouped_prompt_contains_category_headers():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    findings = [
        _make_finding2("trend_decline"),
        _make_finding2("anomaly_high"),
        _make_finding2("cusum_shift", extra={"shift_date": "2024-01-15", "direction": "down",
                                              "before_avg": 200.0, "after_avg": 100.0}),
    ]
    interp = LLMInterpreter(llm=None)
    prompt = interp._build_prompt(findings, _make_ctx_for_prompt())
    assert "Trend" in prompt
    assert "Anomali" in prompt or "Kalıcı Değişim" in prompt


def test_key_dates_section_added_when_cusum_present():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    findings = [
        _make_finding2("cusum_shift", extra={"shift_date": "2024-01-15", "direction": "down",
                                              "before_avg": 200.0, "after_avg": 100.0}),
    ]
    prompt = LLMInterpreter(llm=None)._build_prompt(findings, _make_ctx_for_prompt())
    assert "2024-01-15" in prompt


def test_correlation_section_added_when_correlation_present():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    findings = [
        _make_finding2("high_positive_correlation", value="Espresso ↔ Americano",
                      extra={"r": 0.89, "product_a": "Espresso", "product_b": "Americano"}),
    ]
    prompt = LLMInterpreter(llm=None)._build_prompt(findings, _make_ctx_for_prompt())
    assert "Espresso" in prompt
    assert "0.89" in prompt or "r=" in prompt.lower()


def test_system_prompt_mentions_collective():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _SYSTEM_PROMPT
    assert "kolektif" in _SYSTEM_PROMPT.lower() or "birleştir" in _SYSTEM_PROMPT.lower() or "bütünsel" in _SYSTEM_PROMPT.lower()


def _make_finding_for_humanize(ftype, value="ESPRESSO", sig=0.67, extra=None, chg=480.5, cur=480000.0, cmp=84200.0):
    from src.graphs.report_agent.insight_engine.models import Finding
    return Finding(
        type=ftype, analyzer="TestAnalyzer", dimension="ProductName",
        value=value, metric="RowAmount",
        current_value=cur, comparison_value=cmp,
        change_pct=chg, significance=sig, period_label="test",
        extra=extra or {},
    )


def test_risk_badge_levels():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _risk_badge
    assert _risk_badge(0.9) == "🔴"
    assert _risk_badge(0.7) == "🔴"
    assert _risk_badge(0.69) == "🟡"
    assert _risk_badge(0.4) == "🟡"
    assert _risk_badge(0.39) == "🟢"
    assert _risk_badge(0.0) == "🟢"


def test_humanize_anomaly_no_technical_keys():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _humanize_evidence
    f = _make_finding_for_humanize(
        "anomaly_high", extra={"z_score": 2.67, "mean": 84200.0, "std": 150000.0}
    )
    result = _humanize_evidence(f)
    assert "z_score" not in result
    assert "r_squared" not in result
    assert "significance" not in result
    assert "84" in result or "normal" in result.lower()


def test_humanize_cusum_includes_date():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _humanize_evidence
    f = _make_finding_for_humanize(
        "cusum_shift", value="2024-01-15",
        extra={"shift_date": "2024-01-15", "direction": "up",
               "before_avg": 450000.0, "after_avg": 4200000.0},
        chg=837.0, cur=4200000.0, cmp=450000.0,
    )
    result = _humanize_evidence(f)
    assert "2024-01-15" in result
    assert "z_score" not in result


def test_humanize_trend_no_r_squared():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _humanize_evidence
    f = _make_finding_for_humanize(
        "trend_decline", chg=-32.5, cur=670.0, cmp=993.0,
        extra={"slope": -10.2, "r_squared": 0.84, "mk_trend": "decreasing", "mk_tau": -0.72},
    )
    result = _humanize_evidence(f)
    assert "r_squared" not in result
    assert "mk_trend" not in result
    assert "slope" not in result
    assert "-32.5" in result or "düşüş" in result.lower()


def test_humanize_wow_includes_both_periods():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _humanize_evidence
    f = _make_finding_for_humanize(
        "wow_surge", chg=150.0, cur=1200000.0, cmp=480000.0,
        extra={"last7_sum": 1200000.0, "prev7_sum": 480000.0},
    )
    result = _humanize_evidence(f)
    assert "1.20M" in result or "1200" in result
    assert "480" in result


def test_humanize_correlation_no_r_key():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _humanize_evidence
    f = _make_finding_for_humanize(
        "high_positive_correlation", value="Espresso ↔ Americano",
        extra={"r": 0.89, "product_a": "Espresso", "product_b": "Americano"},
        chg=0.0, cur=100.0, cmp=80.0,
    )
    result = _humanize_evidence(f)
    assert "'r'" not in result
    assert "Espresso" in result
    assert "Americano" in result


def test_finding_labels_covers_all_types():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _FINDING_LABELS
    required_types = [
        "trend_increase", "trend_decline", "anomaly_high", "anomaly_low",
        "cusum_shift", "regime_change", "wow_surge", "wow_drop", "high_momentum",
        "high_volatility", "accelerating", "decelerating", "seasonal_peak",
        "seasonal_trough", "top_performer", "bottom_performer", "pareto_dominant",
        "bcg_star", "bcg_dog", "peak_period", "weak_period",
        "high_positive_correlation", "high_negative_correlation",
    ]
    for t in required_types:
        assert t in _FINDING_LABELS, f"Missing label for: {t}"
        assert "_" not in _FINDING_LABELS[t], f"Label has underscore: {_FINDING_LABELS[t]}"
