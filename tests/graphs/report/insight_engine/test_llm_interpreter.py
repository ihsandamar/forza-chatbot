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
