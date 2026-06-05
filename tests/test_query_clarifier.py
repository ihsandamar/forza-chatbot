import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.graphs.report_agent.subagents.query_clarifier.prompts import (
    ClarityAnalysisResult,
    ClarityIssue,
)


def _make_llm(result: ClarityAnalysisResult) -> MagicMock:
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=result)
    return mock_llm


def _high_clarity_result() -> ClarityAnalysisResult:
    return ClarityAnalysisResult(
        clarity_score=0.90,
        issues=[],
        suggested_query=None,
        suggestion_message=None,
        can_suggest=False,
    )


def _low_clarity_result() -> ClarityAnalysisResult:
    return ClarityAnalysisResult(
        clarity_score=0.50,
        issues=[
            ClarityIssue(
                type="missing_date_filter",
                description="Tarih filtresi yok",
                severity="high",
            )
        ],
        suggested_query="Bu ayki CategoryName bazında toplam RowAmount",
        suggestion_message=(
            "Şunu mu sormak istediniz?\n\n"
            "📊 Bu ayki CategoryName bazında toplam RowAmount\n\n"
            "Evet ise onaylayın, değilse 'hayır' yazın."
        ),
        can_suggest=True,
    )


def _vague_result() -> ClarityAnalysisResult:
    return ClarityAnalysisResult(
        clarity_score=0.0,
        issues=[
            ClarityIssue(
                type="missing_date_filter",
                description="Tarih filtresi yok",
                severity="high",
            ),
            ClarityIssue(
                type="missing_grouping",
                description="Gruplama belirtilmemiş",
                severity="high",
            ),
        ],
        suggested_query="Bu ayki CategoryName bazında toplam RowAmount, büyükten küçüğe",
        suggestion_message=(
            "Şunu mu sormak istediniz?\n\n"
            "📊 Bu ayki CategoryName bazında toplam RowAmount, büyükten küçüğe\n\n"
            "Evet ise onaylayın, değilse 'hayır' yazın."
        ),
        can_suggest=True,
    )


# --- Tests ---


@pytest.mark.asyncio
async def test_clarifier_disabled_returns_pass():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    node = create_clarity_analyzer_node(
        MagicMock(), clarity_threshold=0.65, enable_clarifier=False
    )
    result = await node({"user_query": "satışları göster", "intent_type": "NEW_QUERY"})
    assert result == {"clarifier_decision": "PASS"}


@pytest.mark.asyncio
async def test_high_clarity_score_passes_without_interrupt():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    node = create_clarity_analyzer_node(
        _make_llm(_high_clarity_result()),
        clarity_threshold=0.65,
        enable_clarifier=True,
    )
    result = await node(
        {
            "user_query": "Ocak 2025 BranchName bazında RowAmount toplamı",
            "intent_type": "NEW_QUERY",
        }
    )
    assert result == {"clarifier_decision": "PASS"}


@pytest.mark.asyncio
async def test_low_clarity_user_accepts_updates_query():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    node = create_clarity_analyzer_node(
        _make_llm(_low_clarity_result()),
        clarity_threshold=0.65,
        enable_clarifier=True,
    )

    with patch(
        "src.graphs.report_agent.subagents.query_clarifier.nodes.interrupt",
        return_value="Evet, devam et",
    ):
        result = await node({"user_query": "kategorilere bak", "intent_type": "NEW_QUERY"})

    assert result["clarifier_decision"] == "CLARIFIED"
    assert result["user_query"] == "Bu ayki CategoryName bazında toplam RowAmount"
    assert result["suggested_query"] == "Bu ayki CategoryName bazında toplam RowAmount"


@pytest.mark.asyncio
async def test_low_clarity_user_rejects_returns_pass():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    node = create_clarity_analyzer_node(
        _make_llm(_low_clarity_result()),
        clarity_threshold=0.65,
        enable_clarifier=True,
    )

    with patch(
        "src.graphs.report_agent.subagents.query_clarifier.nodes.interrupt",
        return_value="Hayır",
    ):
        result = await node({"user_query": "kategorilere bak", "intent_type": "NEW_QUERY"})

    assert result == {"clarifier_decision": "PASS"}


@pytest.mark.asyncio
async def test_vague_query_always_triggers_suggestion():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    node = create_clarity_analyzer_node(
        _make_llm(_vague_result()),
        clarity_threshold=0.65,
        enable_clarifier=True,
    )

    with patch(
        "src.graphs.report_agent.subagents.query_clarifier.nodes.interrupt",
        return_value="Evet, devam et",
    ) as mock_interrupt:
        result = await node({"user_query": "satışlar", "intent_type": "VAGUE_QUERY"})

    mock_interrupt.assert_called_once()
    assert result["clarifier_decision"] == "CLARIFIED"


@pytest.mark.asyncio
async def test_vague_query_user_rejects_returns_pass():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    node = create_clarity_analyzer_node(
        _make_llm(_vague_result()),
        clarity_threshold=0.65,
        enable_clarifier=True,
    )

    with patch(
        "src.graphs.report_agent.subagents.query_clarifier.nodes.interrupt",
        return_value="hayır",
    ):
        result = await node({"user_query": "satışlar", "intent_type": "VAGUE_QUERY"})

    assert result == {"clarifier_decision": "PASS"}


@pytest.mark.asyncio
async def test_llm_failure_returns_pass_silently():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.ainvoke = AsyncMock(
        side_effect=Exception("LLM zaman aşımı")
    )

    node = create_clarity_analyzer_node(
        mock_llm, clarity_threshold=0.65, enable_clarifier=True
    )
    result = await node({"user_query": "test", "intent_type": "NEW_QUERY"})
    assert result == {"clarifier_decision": "PASS"}


@pytest.mark.asyncio
async def test_no_suggestion_available_skips_interrupt():
    from src.graphs.report_agent.subagents.query_clarifier.nodes import (
        create_clarity_analyzer_node,
    )

    result_no_suggest = ClarityAnalysisResult(
        clarity_score=0.50,
        issues=[
            ClarityIssue(type="ambiguous_metric", description="Metrik belirsiz", severity="medium")
        ],
        suggested_query=None,
        suggestion_message=None,
        can_suggest=False,
    )

    node = create_clarity_analyzer_node(
        _make_llm(result_no_suggest),
        clarity_threshold=0.65,
        enable_clarifier=True,
    )

    with patch(
        "src.graphs.report_agent.subagents.query_clarifier.nodes.interrupt"
    ) as mock_interrupt:
        result = await node({"user_query": "satış ne oldu", "intent_type": "NEW_QUERY"})

    mock_interrupt.assert_not_called()
    assert result == {"clarifier_decision": "PASS"}


# --- Router tests (tested after Task 5 implements _clarifier_router) ---


def test_clarifier_router_new_query_pass():
    from src.graphs.report_agent.graph import _clarifier_router

    assert _clarifier_router({"intent_type": "NEW_QUERY", "clarifier_decision": "PASS"}) == "text2sql"


def test_clarifier_router_new_query_clarified():
    from src.graphs.report_agent.graph import _clarifier_router

    assert _clarifier_router({"intent_type": "NEW_QUERY", "clarifier_decision": "CLARIFIED"}) == "text2sql"


def test_clarifier_router_modify_query():
    from src.graphs.report_agent.graph import _clarifier_router

    assert _clarifier_router({"intent_type": "MODIFY_QUERY", "clarifier_decision": "PASS"}) == "modify_sql"
    assert _clarifier_router({"intent_type": "MODIFY_QUERY", "clarifier_decision": "CLARIFIED"}) == "modify_sql"


def test_clarifier_router_vague_pass_goes_to_report_chat():
    from src.graphs.report_agent.graph import _clarifier_router

    assert _clarifier_router({"intent_type": "VAGUE_QUERY", "clarifier_decision": "PASS"}) == "report_chat"


def test_clarifier_router_vague_clarified_goes_to_text2sql():
    from src.graphs.report_agent.graph import _clarifier_router

    assert _clarifier_router({"intent_type": "VAGUE_QUERY", "clarifier_decision": "CLARIFIED"}) == "text2sql"
