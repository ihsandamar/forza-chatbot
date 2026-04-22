"""
ValueResolverService.resolve_column_name() should work before initialize() is called
— semantic map must be ready in __init__.
"""
from unittest.mock import MagicMock, patch


def _make_vrs():
    from src.graphs.report_agent.subagents.text2sql.value_resolver_service import ValueResolverService
    with patch("pyodbc.connect", MagicMock()):
        vrs = ValueResolverService(
            db_connection_string="mssql+pyodbc://user:pass@host/db?driver=ODBC+Driver+17+for+SQL+Server",
            table_name="TestTable",
        )
    return vrs


def test_resolve_column_name_works_before_initialize():
    """initialize() not called → resolve_column_name() should still resolve Turkish names."""
    vrs = _make_vrs()
    assert vrs.resolve_column_name("Kategori") == "CategoryName"
    assert vrs.resolve_column_name("tutar") == "RowAmount"
    assert vrs.resolve_column_name("Sube") == "BranchName"


def test_resolve_column_name_returns_none_for_unknown():
    vrs = _make_vrs()
    assert vrs.resolve_column_name("xyzunknown") is None
