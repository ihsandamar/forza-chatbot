"""Tests for aggregate period granularity (hour_of_day, day_of_week, day_of_month)."""
import pytest


class TestTimeGranMap:
    """Verify _TIME_GRAN_MAP entries for aggregate period types."""

    def test_hour_of_day_has_no_date(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP
        cols = _TIME_GRAN_MAP["hour_of_day"]
        assert cols == ["DATEPART(HOUR, DocumentDate)"]
        assert not any("CAST(" in c for c in cols), "hour_of_day must NOT include date"

    def test_day_of_week_has_no_date(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP
        cols = _TIME_GRAN_MAP["day_of_week"]
        assert cols == ["DATEPART(DW, DocumentDate)"]
        assert not any("CAST(" in c for c in cols), "day_of_week must NOT include date"

    def test_day_of_month_has_no_date(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP
        cols = _TIME_GRAN_MAP["day_of_month"]
        assert cols == ["DATEPART(DAY, DocumentDate)"]
        assert not any("CAST(" in c for c in cols), "day_of_month must NOT include date"

    def test_existing_hourly_unchanged(self):
        """hourly (time-series) must still include date + hour."""
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP
        cols = _TIME_GRAN_MAP["hourly"]
        assert "CAST(DocumentDate AS DATE)" in cols
        assert "DATEPART(HOUR, DocumentDate)" in cols


class TestExprAliasMap:
    """Verify SELECT aliases for aggregate period expressions."""

    def test_hour_of_day_alias(self):
        from src.graphs.report_agent.subagents.text2sql.sql_builder import _EXPR_ALIAS_MAP
        assert _EXPR_ALIAS_MAP["DATEPART(HOUR, DocumentDate)"] == "Saat"

    def test_day_of_week_alias(self):
        from src.graphs.report_agent.subagents.text2sql.sql_builder import _EXPR_ALIAS_MAP
        assert _EXPR_ALIAS_MAP["DATEPART(DW, DocumentDate)"] == "HaftaGunu"

    def test_day_of_month_alias(self):
        from src.graphs.report_agent.subagents.text2sql.sql_builder import _EXPR_ALIAS_MAP
        assert _EXPR_ALIAS_MAP["DATEPART(DAY, DocumentDate)"] == "AyinGunu"
