import pytest
from src.graphs.report_agent.progress_mapper import (
    normalize_node_name,
    get_progress_info,
    TOTAL_STEPS,
    NODE_PROGRESS_MESSAGES,
)


def test_normalize_strips_subgraph_prefix():
    assert normalize_node_name("text2sql:sql_executor") == "sql_executor"


def test_normalize_leaves_plain_name_unchanged():
    assert normalize_node_name("sql_executor") == "sql_executor"


def test_normalize_handles_deep_prefix():
    assert normalize_node_name("a:b:c") == "c"


def test_get_progress_info_known_node_returns_tuple():
    result = get_progress_info("sql_executor")
    assert result is not None
    node_name, message, index = result
    assert node_name == "sql_executor"
    assert "çekiliyor" in message
    assert index == 9


def test_get_progress_info_unknown_node_returns_none():
    assert get_progress_info("__graph_start__") is None


def test_get_progress_info_normalizes_prefix():
    plain = get_progress_info("sql_executor")
    prefixed = get_progress_info("text2sql:sql_executor")
    assert plain == prefixed


def test_get_progress_info_retry_message_on_second_occurrence():
    _, message, _ = get_progress_info("semantic_extractor", occurrence_count=2)
    assert "yeniden" in message


def test_total_steps_is_thirteen():
    assert TOTAL_STEPS == 13


def test_all_expected_nodes_present():
    expected = {
        "classify_intent", "modify_sql", "report_chat",
        "create_table", "business_rules", "semantic_extractor",
        "term_resolver", "term_validator", "schema_builder",
        "value_resolver", "sql_generator", "sql_executor",
        "data_analyzer", "template_renderer", "build_response",
    }
    assert expected == set(NODE_PROGRESS_MESSAGES.keys())
