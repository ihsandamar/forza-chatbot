import pytest
from unittest.mock import AsyncMock, MagicMock


def test_semantic_extractor_node_writes_semantic_intent():
    """semantic_extractor_node writes model_dump() to state['semantic_intent']."""
    import asyncio
    from src.graphs.report_agent.subagents.text2sql.nodes import create_semantic_extractor_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    expected_intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="dürümler", entity_type="filter_value")],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="dürümler ciro",
    )
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=expected_intent)

    node = create_semantic_extractor_node(mock_llm, {})
    state = {
        "user_query": "dürümler ciro",
        "query_type": "SINGLE",
        "messages": [],
        "sql_error": None,
    }
    result = asyncio.get_event_loop().run_until_complete(node(state))
    assert "semantic_intent" in result
    assert result["semantic_intent"]["raw_query"] == "dürümler ciro"


def test_schema_builder_node_writes_query_schema():
    """schema_builder_node converts semantic_intent + term_resolution → query_schema dict."""
    import asyncio
    from datetime import date
    from src.graphs.report_agent.subagents.text2sql.nodes import create_schema_builder_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticMetric, TermMatch,
    )
    intent = SemanticIntent(
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="ciro",
    )
    term_resolution = {"ciro": TermMatch(column_name="RowAmount", filter_structured=None,
                                         specificity=1.0, similarity=0.95)}
    state = {
        "semantic_intent": intent.model_dump(),
        "term_resolution": {"ciro": {"column_name": "RowAmount", "filter_structured": None,
                                      "specificity": 1.0, "similarity": 0.95}},
        "query_type": "SINGLE",
        "time_breakdown": False,
    }
    node = create_schema_builder_node()
    result = asyncio.get_event_loop().run_until_complete(node(state))
    assert "query_schema" in result
    assert result["query_schema"] is not None


def test_prompt_contains_filter_value_raw_text_rule():
    """SEMANTIC_EXTRACTOR_PROMPT filter_value için saf değer (ek-siz) ve zorunlu column_hint kuralını içermeli."""
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    prompt_lower = SEMANTIC_EXTRACTOR_PROMPT.lower()
    assert "zorunlu" in prompt_lower or "mandatory" in prompt_lower


def test_prompt_contains_category_example_with_column_hint():
    """SEMANTIC_EXTRACTOR_PROMPT espresso/dürümler + CategoryName örneği içermeli."""
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    assert "CategoryName" in SEMANTIC_EXTRACTOR_PROMPT
    assert "espresso" in SEMANTIC_EXTRACTOR_PROMPT and "dürümler" in SEMANTIC_EXTRACTOR_PROMPT


def test_semantic_time_accepts_granularity_field():
    """SemanticTime granularity alanını kabul etmeli."""
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="son 1 senede", breakdown=True, granularity="monthly")
    assert st.granularity == "monthly"


def test_semantic_time_granularity_defaults_to_none():
    """granularity verilmezse None olmalı (backward compat)."""
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="son 3 ay", breakdown=False)
    assert st.granularity is None


def test_prompt_contains_granularity_rule():
    """SEMANTIC_EXTRACTOR_PROMPT, 'aylık' → 'monthly' kuralını içermeli."""
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    prompt_lower = SEMANTIC_EXTRACTOR_PROMPT.lower()
    assert "granularity" in prompt_lower
    assert "monthly" in prompt_lower
    assert "weekly" in prompt_lower
    assert "aylık" in prompt_lower


def test_prompt_mandates_canonical_raw_text():
    """
    SEMANTIC_EXTRACTOR_PROMPT must contain an explicit rule that raw_text
    is the canonical root form for ALL entity types. Python does not strip suffixes.
    """
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    assert "raw_text = KANONİK KÖK FORM" in SEMANTIC_EXTRACTOR_PROMPT
    assert "platformlara" in SEMANTIC_EXTRACTOR_PROMPT
    assert "YASAK" in SEMANTIC_EXTRACTOR_PROMPT


def test_prompt_mandates_column_hint_for_dimension():
    """
    column_hint must be declared ZORUNLU for dimension entities,
    not just shown in examples.
    """
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    dim_idx = SEMANTIC_EXTRACTOR_PROMPT.find('"dimension"')
    assert dim_idx != -1
    dim_section = SEMANTIC_EXTRACTOR_PROMPT[dim_idx:dim_idx + 400]
    assert "ZORUNLU" in dim_section, "column_hint must be declared ZORUNLU for dimension entities"


def test_semantic_extractor_node_uses_column_metadata_closure():
    """
    column_metadata is injected as a closure, not read from state.
    The LLM prompt must contain the column names from the catalog,
    so the LLM can produce correct column_hint for unknown terms like 'şube grubu'.
    """
    import asyncio
    from unittest.mock import call as mock_call
    from src.graphs.report_agent.subagents.text2sql.nodes import create_semantic_extractor_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticIntent

    col_meta = {
        "BranchGroupName": "Şube grubu / grup adı",
        "BranchName": "Şube adı",
        "RowAmount": "Satış tutarı",
    }

    mock_llm = MagicMock()
    captured_prompts = []

    async def capture_invoke(prompt):
        captured_prompts.append(prompt)
        return SemanticIntent(raw_query="test")

    mock_llm.with_structured_output.return_value.ainvoke = capture_invoke

    node = create_semantic_extractor_node(mock_llm, col_meta)
    state = {"user_query": "şube grubu ciro", "query_type": "SINGLE", "messages": [], "sql_error": None}
    asyncio.get_event_loop().run_until_complete(node(state))

    assert captured_prompts, "LLM was not invoked"
    prompt_text = captured_prompts[0]
    assert "BranchGroupName" in prompt_text, "column_metadata not in prompt — architecture gap still present"
    assert "BranchName" in prompt_text
    assert "Bilinmiyor" not in prompt_text


def test_prompt_mandates_column_hint_for_comparison_value():
    """
    column_hint must be declared ZORUNLU for comparison_value entities.
    """
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    cv_idx = SEMANTIC_EXTRACTOR_PROMPT.find('"comparison_value"')
    assert cv_idx != -1
    cv_section = SEMANTIC_EXTRACTOR_PROMPT[cv_idx:cv_idx + 400]
    assert "ZORUNLU" in cv_section, "column_hint must be declared ZORUNLU for comparison_value entities"
