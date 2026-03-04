"""SQL expression GROUP BY kolonlarının SELECT'te alias almasını doğrula."""
from datetime import date

import pytest

from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql


def _make_schema(**overrides) -> dict:
    base = {
        "filters": [],
        "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamSatis"}],
        "group_by": [],
        "select_columns": [],
        "order_by_column": None,
        "order_by_direction": "DESC",
        "limit": None,
    }
    base.update(overrides)
    return base


TODAY = date(2026, 3, 4)
TABLE = "MasterReportDocumentTable"


def test_year_month_group_by_has_aliases():
    """YEAR(DocumentDate), MONTH(DocumentDate) SELECT'te alias ile görünmeli."""
    schema = _make_schema(
        group_by=["YEAR(DocumentDate)", "MONTH(DocumentDate)"],
    )
    sql = generate_sql(schema, TABLE, [], TODAY)

    # Alias'lı olmalı
    assert "AS [" in sql, f"GROUP BY expression'ları alias almalı: {sql}"
    # YEAR ve MONTH alias'ları var mı?
    assert "YEAR(DocumentDate) AS [" in sql, f"YEAR alias eksik: {sql}"
    assert "MONTH(DocumentDate) AS [" in sql, f"MONTH alias eksik: {sql}"


def test_cast_date_group_by_has_alias():
    """CAST(DocumentDate AS DATE) SELECT'te alias ile görünmeli."""
    schema = _make_schema(
        group_by=["CAST(DocumentDate AS DATE)"],
    )
    sql = generate_sql(schema, TABLE, [], TODAY)
    assert "CAST(DocumentDate AS DATE) AS [" in sql, f"CAST alias eksik: {sql}"


def test_simple_column_group_by_no_double_alias():
    """Basit kolon adı (ProductName) alias almadan [bracket] ile görünmeli."""
    schema = _make_schema(
        group_by=["ProductName"],
    )
    sql = generate_sql(schema, TABLE, [], TODAY)
    assert "[ProductName]" in sql
    # Basit kolonlara ek alias eklenmemeli
    assert "[ProductName] AS" not in sql, f"Basit kolona alias eklenmemeli: {sql}"


def test_datepart_week_has_alias():
    """DATEPART(WEEK, DocumentDate) SELECT'te alias ile görünmeli."""
    schema = _make_schema(
        group_by=["YEAR(DocumentDate)", "DATEPART(WEEK, DocumentDate)"],
    )
    sql = generate_sql(schema, TABLE, [], TODAY)
    assert "DATEPART(WEEK, DocumentDate) AS [" in sql, f"DATEPART alias eksik: {sql}"


def test_mixed_group_by_expressions_and_columns():
    """Expression + basit kolon karışık GROUP BY — her ikisi doğru formatlanmalı."""
    schema = _make_schema(
        group_by=["CategoryName", "YEAR(DocumentDate)", "MONTH(DocumentDate)"],
    )
    sql = generate_sql(schema, TABLE, [], TODAY)
    assert "[CategoryName]" in sql
    assert "[CategoryName] AS" not in sql  # basit kolona alias yok
    assert "YEAR(DocumentDate) AS [" in sql
    assert "MONTH(DocumentDate) AS [" in sql
