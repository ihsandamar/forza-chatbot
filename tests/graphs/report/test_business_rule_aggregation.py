"""Tests for business rule aggregation template with {column} placeholder."""

import json
from datetime import date
from pathlib import Path

from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql


def _load_default_rules() -> list:
    """Load business rules and return only default rules (matching sql_generator behavior)."""
    rules_path = Path(__file__).parents[3] / "src" / "graphs" / "report_agent" / "data" / "business_rules.json"
    with open(rules_path, encoding="utf-8") as f:
        data = json.load(f)
    return [r for r in data["business_logic_rules"] if r.get("is_default")]


class TestBusinessRuleAggregation:
    """iade_dusulmus rule must use {column} placeholder, not hardcoded RowAmount."""

    def test_quantity_aggregation_uses_quantity_column(self):
        """SUM(Quantity) should produce CASE WHEN with [Quantity], not [RowAmount]."""
        schema = {
            "aggregations": [
                {"function": "SUM", "column": "Quantity", "alias": "ToplamAdet"}
            ],
            "filters": [],
            "group_by": ["CategoryName"],
            "select_columns": [],
            "order_by_column": None,
            "order_by_direction": None,
            "limit": None,
        }
        rules = _load_default_rules()
        sql = generate_sql(schema, "MasterReportDocumentTable", rules, date(2026, 3, 5))

        assert "[Quantity]" in sql, f"SQL should contain [Quantity] but got: {sql}"
        assert "AS [ToplamAdet]" in sql
        assert "[RowAmount]" not in sql, f"SQL should NOT contain [RowAmount] but got: {sql}"

    def test_row_amount_aggregation_uses_row_amount_column(self):
        """SUM(RowAmount) should still produce CASE WHEN with [RowAmount]."""
        schema = {
            "aggregations": [
                {"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}
            ],
            "filters": [],
            "group_by": ["CategoryName"],
            "select_columns": [],
            "order_by_column": None,
            "order_by_direction": None,
            "limit": None,
        }
        rules = _load_default_rules()
        sql = generate_sql(schema, "MasterReportDocumentTable", rules, date(2026, 3, 5))

        assert "[RowAmount]" in sql
        assert "AS [ToplamCiro]" in sql
        assert "DocumentTypeIsReturn" in sql

    def test_mixed_aggregation_uses_correct_columns(self):
        """Query with both SUM(Quantity) and SUM(RowAmount) should use respective columns."""
        schema = {
            "aggregations": [
                {"function": "SUM", "column": "Quantity", "alias": "ToplamAdet"},
                {"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"},
            ],
            "filters": [],
            "group_by": ["CategoryName"],
            "select_columns": [],
            "order_by_column": None,
            "order_by_direction": None,
            "limit": None,
        }
        rules = _load_default_rules()
        sql = generate_sql(schema, "MasterReportDocumentTable", rules, date(2026, 3, 5))

        assert "[Quantity]" in sql, f"SQL should contain [Quantity]: {sql}"
        assert "[RowAmount]" in sql, f"SQL should contain [RowAmount]: {sql}"
        assert "AS [ToplamAdet]" in sql
        assert "AS [ToplamCiro]" in sql

    def test_count_aggregation_not_affected_by_rule(self):
        """COUNT aggregations should NOT be wrapped with the business rule."""
        schema = {
            "aggregations": [
                {"function": "COUNT", "column": "DocumentId", "alias": "ToplamAdisyon"}
            ],
            "filters": [],
            "group_by": [],
            "select_columns": [],
            "order_by_column": None,
            "order_by_direction": None,
            "limit": None,
        }
        rules = _load_default_rules()
        sql = generate_sql(schema, "MasterReportDocumentTable", rules, date(2026, 3, 5))

        assert "COUNT([DocumentId])" in sql
        assert "DocumentTypeIsReturn" not in sql
