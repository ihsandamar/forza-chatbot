"""COMPARISON sorgularda çakışan business rule filtrelerinin IN'e dönüştürülmesini doğrula."""
import pytest
from datetime import date


def test_comparison_conflicting_rules_merged_to_in():
    """
    COMPARISON: kapali_masa + acik_masa auto_rules → [IsTableActive] = 0 AND = 1
    yerine schema'ya IN ('0', '1') eklenmeli ve rule filter'lar strip edilmeli.
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import (
        _merge_conflicting_rule_filters_for_comparison,
    )

    raw_schema = {
        "filters": [
            {
                "column": "IsTableActive",
                "operator": "IN",
                "values": ["0", "1"],
                "logical_operator": "AND",
            },
        ],
        "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
        "group_by": ["IsTableActive"],
    }

    auto_rules = [
        {
            "id": "iade_dusulmus",
            "is_default": True,
            "sql": {
                "aggregation": "SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END)",
                "filter": None,
            },
        },
        {
            "id": "kapali_masa_filtre",
            "is_default": False,
            "sql": {"filter": "[IsTableActive] = 0", "aggregation": None},
        },
        {
            "id": "acik_masa_filtre",
            "is_default": False,
            "sql": {"filter": "[IsTableActive] = 1", "aggregation": None},
        },
    ]

    new_schema, new_rules = _merge_conflicting_rule_filters_for_comparison(
        raw_schema, auto_rules
    )

    # Çakışan rule filter'lar kaldırılmış olmalı
    for rule in new_rules:
        rule_filter = (rule.get("sql") or {}).get("filter")
        if rule_filter:
            assert "IsTableActive" not in rule_filter, \
                f"Rule '{rule['id']}' hâlâ IsTableActive filtresi taşıyor: {rule_filter}"

    # Schema'da IsTableActive IN filtresi olmalı
    is_table_filters = [
        f for f in new_schema["filters"]
        if f.get("column") == "IsTableActive"
    ]
    assert len(is_table_filters) == 1, \
        f"Tek bir IsTableActive filtresi olmalı, bulundu: {len(is_table_filters)}"
    assert is_table_filters[0]["operator"] == "IN"
    assert set(is_table_filters[0]["values"]) == {"0", "1"}


def test_comparison_conflicting_rules_generates_valid_sql():
    """Çakışan kurallar dönüştürüldükten sonra geçerli SQL üretilmeli."""
    from src.graphs.report_agent.subagents.text2sql.nodes import (
        _merge_conflicting_rule_filters_for_comparison,
    )
    from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql

    raw_schema = {
        "filters": [],
        "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
        "group_by": ["IsTableActive"],
        "select_columns": [],
        "order_by_column": "ToplamCiro",
        "order_by_direction": "DESC",
        "limit": None,
    }

    auto_rules = [
        {
            "id": "kapali_masa_filtre",
            "is_default": False,
            "sql": {"filter": "[IsTableActive] = 0", "aggregation": None},
        },
        {
            "id": "acik_masa_filtre",
            "is_default": False,
            "sql": {"filter": "[IsTableActive] = 1", "aggregation": None},
        },
    ]

    new_schema, new_rules = _merge_conflicting_rule_filters_for_comparison(
        raw_schema, auto_rules
    )

    sql = generate_sql(new_schema, "MasterReportDocumentTable", new_rules, date(2026, 3, 4))

    assert "[IsTableActive] IN" in sql, f"IN filtresi olmalı: {sql}"
    # İmkansız koşul olmamalı
    assert not ("[IsTableActive] = 0" in sql and "[IsTableActive] = 1" in sql), \
        f"Çakışan AND koşulları hâlâ var: {sql}"


def test_non_comparison_rules_untouched():
    """Tek-rule'lu durumda değişiklik yapmamalı."""
    from src.graphs.report_agent.subagents.text2sql.nodes import (
        _merge_conflicting_rule_filters_for_comparison,
    )

    raw_schema = {"filters": []}
    auto_rules = [
        {"id": "kapali_masa_filtre", "sql": {"filter": "[IsTableActive] = 0"}},
    ]

    new_schema, new_rules = _merge_conflicting_rule_filters_for_comparison(
        raw_schema, auto_rules
    )

    # Tek kural — çakışma yok — değişiklik olmamalı
    assert new_rules[0]["sql"]["filter"] == "[IsTableActive] = 0"
    assert len(new_schema["filters"]) == 0
