"""Integration tests for aggregate period granularity through SQL generation."""
import pytest
from datetime import date


class TestAggregatePeriodSQLGeneration:
    """Test that aggregate period granularities produce correct SQL GROUP BY."""

    def test_hour_of_day_no_date_in_sql(self):
        """hour_of_day must produce SQL with only DATEPART(HOUR) in GROUP BY, no date."""
        from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP

        group_by = _TIME_GRAN_MAP["hour_of_day"]
        schema = {
            "select_columns": [],
            "filters": [{"column": "CategoryName", "operator": "=", "value": "ESPRESSO", "logical_operator": "AND"}],
            "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
            "group_by": group_by,
            "order_by_column": None,
            "order_by_direction": "ASC",
            "limit": None,
        }
        sql = generate_sql(schema, "MasterReportDocumentTable", [], date(2026, 3, 11))
        sql_upper = sql.upper()

        assert "DATEPART(HOUR" in sql_upper
        assert "CAST(DOCUMENTDATE AS DATE)" not in sql_upper
        assert "GROUP BY" in sql_upper

    def test_day_of_week_no_date_in_sql(self):
        """day_of_week must produce SQL with only DATEPART(DW) in GROUP BY."""
        from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP

        group_by = _TIME_GRAN_MAP["day_of_week"]
        schema = {
            "select_columns": [],
            "filters": [],
            "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
            "group_by": group_by,
            "order_by_column": None,
            "order_by_direction": "ASC",
            "limit": None,
        }
        sql = generate_sql(schema, "MasterReportDocumentTable", [], date(2026, 3, 11))
        sql_upper = sql.upper()

        assert "DATEPART(DW" in sql_upper
        assert "CAST(DOCUMENTDATE AS DATE)" not in sql_upper

    def test_day_of_month_no_date_in_sql(self):
        """day_of_month must produce SQL with only DATEPART(DAY) in GROUP BY."""
        from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP

        group_by = _TIME_GRAN_MAP["day_of_month"]
        schema = {
            "select_columns": [],
            "filters": [],
            "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
            "group_by": group_by,
            "order_by_column": None,
            "order_by_direction": "ASC",
            "limit": None,
        }
        sql = generate_sql(schema, "MasterReportDocumentTable", [], date(2026, 3, 11))
        sql_upper = sql.upper()

        assert "DATEPART(DAY" in sql_upper
        assert "CAST(DOCUMENTDATE AS DATE)" not in sql_upper

    def test_hourly_still_has_date(self):
        """Existing hourly (time-series) must still include date + hour."""
        from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP

        group_by = _TIME_GRAN_MAP["hourly"]
        schema = {
            "select_columns": [],
            "filters": [],
            "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
            "group_by": group_by,
            "order_by_column": None,
            "order_by_direction": "ASC",
            "limit": None,
        }
        sql = generate_sql(schema, "MasterReportDocumentTable", [], date(2026, 3, 11))
        sql_upper = sql.upper()

        assert "CAST(DOCUMENTDATE AS DATE)" in sql_upper
        assert "DATEPART(HOUR" in sql_upper

    def test_hour_of_day_has_correct_alias(self):
        """hour_of_day SELECT should use alias 'Saat'."""
        from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP

        group_by = _TIME_GRAN_MAP["hour_of_day"]
        schema = {
            "select_columns": [],
            "filters": [],
            "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
            "group_by": group_by,
            "order_by_column": None,
            "order_by_direction": "ASC",
            "limit": None,
        }
        sql = generate_sql(schema, "MasterReportDocumentTable", [], date(2026, 3, 11))

        assert "AS [Saat]" in sql

    def test_day_of_week_has_correct_alias(self):
        """day_of_week SELECT should use alias 'HaftaGunu'."""
        from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql
        from src.graphs.report_agent.subagents.text2sql.nodes import _TIME_GRAN_MAP

        group_by = _TIME_GRAN_MAP["day_of_week"]
        schema = {
            "select_columns": [],
            "filters": [],
            "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
            "group_by": group_by,
            "order_by_column": None,
            "order_by_direction": "ASC",
            "limit": None,
        }
        sql = generate_sql(schema, "MasterReportDocumentTable", [], date(2026, 3, 11))

        assert "AS [HaftaGunu]" in sql
