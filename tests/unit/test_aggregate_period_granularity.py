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


class TestKeywordFallback:
    """Verify Turkish keyword → granularity mapping for fallback detection."""

    @pytest.mark.parametrize("query,expected", [
        # hour_of_day patterns
        ("saate göre ciro ver", "hour_of_day"),
        ("günün saatlerine göre", "hour_of_day"),
        ("saat dağılımı", "hour_of_day"),
        ("saatlere göre satış", "hour_of_day"),
        # day_of_week patterns
        ("haftanın günlerine göre", "day_of_week"),
        ("güne göre dağılım", "day_of_week"),
        ("gün bazında", "daily"),  # existing keyword match for time-series
        # day_of_month patterns
        ("ayın günlerine göre", "day_of_month"),
        # Existing patterns UNCHANGED
        ("saatlik satış trendi", "hourly"),
        ("günlük satışlar", "daily"),
        ("haftalık ciro", "weekly"),
        ("aylık karşılaştır", "monthly"),
    ])
    def test_keyword_to_granularity(self, query, expected):
        from src.graphs.report_agent.subagents.text2sql.nodes import _detect_time_granularity_from_query
        result = _detect_time_granularity_from_query(query)
        assert result == expected, f"Query '{query}' → expected {expected}, got {result}"


class TestAggregateGranularitySet:
    """Verify the AGGREGATE_PERIOD_GRANULARITIES constant is accessible."""

    def test_set_exists_in_nodes(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import AGGREGATE_PERIOD_GRANULARITIES
        assert "hour_of_day" in AGGREGATE_PERIOD_GRANULARITIES
        assert "day_of_week" in AGGREGATE_PERIOD_GRANULARITIES
        assert "day_of_month" in AGGREGATE_PERIOD_GRANULARITIES
        assert "hourly" not in AGGREGATE_PERIOD_GRANULARITIES
        assert "daily" not in AGGREGATE_PERIOD_GRANULARITIES
