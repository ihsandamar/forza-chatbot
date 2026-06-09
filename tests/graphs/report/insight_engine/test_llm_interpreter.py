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
    from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

    ctx = AnalysisContext(
        user_query="trend analizi yap",
        active_filters=[],
        period_label="son 7 gün",
        dimension_columns=["ProductName"],
        metric_columns=["RowAmount"],
    )
    f = Finding(
        type="trend_decline", analyzer="TrendAnalyzer", dimension="ProductName",
        value="Burger", metric="RowAmount",
        current_value=670.0, comparison_value=993.0,
        change_pct=-32.5, significance=0.91, period_label="son 7 gün",
        extra={"slope": -10.2, "r_squared": 0.84},
    )
    prompt = LLMInterpreter(None)._build_prompt([f], ctx)
    assert "Düşüş trendi" in prompt   # human label, not type name
    assert "Burger" in prompt
    assert "-32.5" in prompt


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
    from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

    def _mf2(ftype, sig=0.7, extra=None):
        return Finding(
            type=ftype, analyzer="X", dimension="ProductName", value="V",
            metric="RowAmount", current_value=100.0, comparison_value=80.0,
            change_pct=25.0, significance=sig, period_label="test",
            extra=extra or {},
        )

    ctx = AnalysisContext(
        user_query="neler önemli?", active_filters=[], period_label="test",
        dimension_columns=["ProductName"], metric_columns=["RowAmount"],
    )
    findings = [
        _mf2("trend_decline", sig=0.8),
        _mf2("anomaly_high", sig=0.5),
        _mf2("cusum_shift", sig=0.9, extra={"shift_date": "2024-01-15",
              "direction": "down", "before_avg": 200.0, "after_avg": 100.0}),
    ]
    prompt = LLMInterpreter(None)._build_prompt(findings, ctx)
    assert "🔴" in prompt   # high significance → red badge
    assert "🟡" in prompt   # medium significance → yellow badge


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
    lower = _SYSTEM_PROMPT.lower()
    assert "bütünsel" in lower or "bağlantı" in lower


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
        "seasonal_trough", "periodic_pattern", "top_performer", "bottom_performer",
        "pareto_dominant", "bcg_star", "bcg_cash_cow", "bcg_question_mark",
        "bcg_dog", "peak_period", "weak_period",
        "high_positive_correlation", "high_negative_correlation",
    ]
    for t in required_types:
        assert t in _FINDING_LABELS, f"Missing label for: {t}"
        assert "_" not in _FINDING_LABELS[t], f"Label has underscore: {_FINDING_LABELS[t]}"


def test_system_prompt_bans_technical_terms():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _SYSTEM_PROMPT
    lower = _SYSTEM_PROMPT.lower()
    assert "r²" not in lower
    assert "z-score" not in lower
    assert "teknik" in lower  # has language rules section


def test_system_prompt_has_action_rules():
    from src.graphs.report_agent.insight_engine.llm_interpreter import _SYSTEM_PROMPT
    lower = _SYSTEM_PROMPT.lower()
    assert "maksimum 3" in lower or "max 3" in lower
    assert "fiil" in lower or "aksiyon" in lower


def test_build_prompt_uses_risk_badges():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

    def _f(sig):
        return Finding(
            type="anomaly_high", analyzer="A", dimension="D", value="V",
            metric="M", current_value=500000.0, comparison_value=84000.0,
            change_pct=480.0, significance=sig, period_label="test",
            extra={"z_score": 2.67, "mean": 84000.0},
        )

    ctx = AnalysisContext(
        user_query="analiz et", active_filters=[], period_label="test",
        dimension_columns=["ProductName"], metric_columns=["RowAmount"],
    )
    findings = [_f(0.9), _f(0.5)]
    prompt = LLMInterpreter(None)._build_prompt(findings, ctx)
    assert "🔴" in prompt
    assert "🟡" in prompt


def test_build_prompt_no_raw_extra_dump():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

    ctx = AnalysisContext(
        user_query="analiz", active_filters=[], period_label="test",
        dimension_columns=["ProductName"], metric_columns=["RowAmount"],
    )
    f = Finding(
        type="anomaly_high", analyzer="A", dimension="ProductName", value="ESPRESSO",
        metric="RowAmount", current_value=480000.0, comparison_value=84000.0,
        change_pct=480.5, significance=0.67, period_label="test",
        extra={"z_score": 2.67, "mean": 84000.0, "std": 150000.0},
    )
    prompt = LLMInterpreter(None)._build_prompt([f], ctx)
    assert "'z_score'" not in prompt
    assert "'r_squared'" not in prompt
    assert "'mk_trend'" not in prompt
    assert "84" in prompt or "normalin" in prompt.lower()


def test_user_role_in_prompt_for_branch_manager():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

    ctx = AnalysisContext(
        user_query="analiz et", active_filters=[], period_label="test",
        dimension_columns=["ProductName"], metric_columns=["RowAmount"],
        user_role="branch_manager",
    )
    f = Finding(
        type="top_performer", analyzer="A", dimension="ProductName", value="LATTE",
        metric="RowAmount", current_value=5000.0, comparison_value=1000.0,
        change_pct=400.0, significance=0.8, period_label="test",
        extra={"rank": 1, "total_segments": 10},
    )
    prompt = LLMInterpreter(None)._build_prompt([f], ctx)
    assert "branch_manager" in prompt or "şube müdürü" in prompt.lower()


def test_no_role_gives_no_role_block():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

    ctx = AnalysisContext(
        user_query="analiz et", active_filters=[], period_label="test",
        dimension_columns=["ProductName"], metric_columns=["RowAmount"],
    )
    f = Finding(
        type="top_performer", analyzer="A", dimension="ProductName", value="LATTE",
        metric="RowAmount", current_value=5000.0, comparison_value=1000.0,
        change_pct=400.0, significance=0.8, period_label="test",
        extra={"rank": 1, "total_segments": 10},
    )
    prompt = LLMInterpreter(None)._build_prompt([f], ctx)
    assert "Kullanıcı Rolü" not in prompt


def test_analysis_context_accepts_user_role():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    ctx = AnalysisContext(
        user_query="test", active_filters=[], period_label="test",
        dimension_columns=[], metric_columns=[],
        user_role="general_manager",
    )
    assert ctx.user_role == "general_manager"


def test_analysis_context_user_role_defaults_none():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    ctx = AnalysisContext(
        user_query="test", active_filters=[], period_label="test",
        dimension_columns=[], metric_columns=[],
    )
    assert ctx.user_role is None
