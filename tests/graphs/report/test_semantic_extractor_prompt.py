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
    assert "YANLIŞ (dimension seçersen filtre OLMAZ" in SEMANTIC_EXTRACTOR_PROMPT


def test_prompt_has_group_by_auto_note():
    """Prompt must tell LLM that system auto-adds GROUP BY so LLM only needs filter_value."""
    assert "GROUP BY'ı otomatik ekler" in SEMANTIC_EXTRACTOR_PROMPT


def test_prompt_ranking_requires_dimension_entity():
    """Regression guard: 'en çok ciro yapan ürün hangisidir' (RANKING) must still generate
    a dimension entity for ProductName. The YANLIŞ example in the TIME_SERIES+ZAMIR section
    must not be a global ban on dimension entities — RANKING queries need them for group_by."""
    assert (
        "RANKING'de DOĞRU" in SEMANTIC_EXTRACTOR_PROMPT
        or "RANKING'de ZORUNLU" in SEMANTIC_EXTRACTOR_PROMPT
    ), "Prompt must have a RANKING counterexample showing dimension entity is correct for ranking"
