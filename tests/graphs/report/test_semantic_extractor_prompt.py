"""Tests that SEMANTIC_EXTRACTOR_PROMPT contains the critical rules for cross-turn pronoun resolution."""
from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT


def test_prompt_has_time_series_filter_value_rule():
    """SEMANTIC_EXTRACTOR_PROMPT must explicitly forbid 'dimension' for pronoun refs in TIME_SERIES_COMPARISON."""
    assert "TIME_SERIES_COMPARISON" in SEMANTIC_EXTRACTOR_PROMPT
    assert "filter_value" in SEMANTIC_EXTRACTOR_PROMPT
    # Must have the new dedicated rule section
    assert "TIME_SERIES_COMPARISON + ZAMIR" in SEMANTIC_EXTRACTOR_PROMPT


def test_prompt_has_anti_dimension_example():
    """Prompt must have an explicit WRONG example showing dimension leads to no filter."""
    assert "YANLIŞ" in SEMANTIC_EXTRACTOR_PROMPT


def test_prompt_has_group_by_auto_note():
    """Prompt must tell LLM that system auto-adds GROUP BY so LLM only needs filter_value."""
    assert "otomatik" in SEMANTIC_EXTRACTOR_PROMPT
