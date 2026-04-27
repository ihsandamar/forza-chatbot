"""build_query_context_summary birim testleri."""
from src.graphs.report_agent.context_builder import build_query_context_summary


def test_both_none_returns_default_message():
    assert build_query_context_summary(None, None) == "Önceki bağlam yok."


def test_filters_appear_in_output():
    result = build_query_context_summary(
        None,
        [{"field": "CategoryName", "value": "Kahve"}],
    )
    assert "CategoryName = 'Kahve'" in result


def test_string_values_from_results_appear():
    rows = [{"ProductName": "Latte"}, {"ProductName": "Espresso"}]
    result = build_query_context_summary(rows, None)
    assert "Latte" in result
    assert "Espresso" in result


def test_numeric_values_excluded():
    rows = [{"ProductName": "Latte", "RowAmount": 100.0}]
    result = build_query_context_summary(rows, None)
    assert "100" not in result
    assert "Latte" in result


def test_deduplicates_values():
    rows = [{"ProductName": "Latte"}, {"ProductName": "Latte"}, {"ProductName": "Latte"}]
    result = build_query_context_summary(rows, None)
    assert result.count("Latte") == 1


def test_max_rows_respected():
    rows = [{"Col": f"Val{i}"} for i in range(20)]
    result = build_query_context_summary(rows, None, max_rows=3)
    assert "Val0" in result
    assert "Val3" not in result


def test_filters_with_missing_field_key_skipped():
    result = build_query_context_summary(
        None,
        [{"field": "CategoryName", "value": "Kahve"}, {"value": "orphan"}],
    )
    assert "orphan" not in result
    assert "CategoryName" in result
