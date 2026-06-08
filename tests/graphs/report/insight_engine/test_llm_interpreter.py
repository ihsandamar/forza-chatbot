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
