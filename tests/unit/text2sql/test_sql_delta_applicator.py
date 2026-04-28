"""SqlDeltaApplicator birim testleri."""
import pytest
from src.graphs.report_agent.subagents.text2sql.sql_delta import SqlDeltaApplicator
from src.graphs.report_agent.prompts import FilterDelta, SqlDelta

BASE_SQL = (
    "SELECT TOP 10 [BranchName], SUM([RowAmount]) AS Total "
    "FROM [MasterReportDocumentTable] "
    "WHERE [CategoryName] = 'Kahve' "
    "ORDER BY Total DESC"
)


def _delta(**kwargs) -> SqlDelta:
    return SqlDelta(explanation="test", confidence=0.9, **kwargs)


def test_add_filter_appends_and_to_existing_where():
    d = _delta(add_filters=[FilterDelta(column="BranchName", operator="=", value="'Ankara'")])
    result = SqlDeltaApplicator().apply(BASE_SQL, d)
    assert "[CategoryName] = 'Kahve'" in result
    assert "[BranchName] = 'Ankara'" in result
    assert result.count("WHERE") == 1


def test_add_filter_creates_where_when_absent():
    sql = "SELECT TOP 10 [BranchName] FROM [MasterReportDocumentTable] ORDER BY [BranchName]"
    d = _delta(add_filters=[FilterDelta(column="BranchName", operator="=", value="'Ankara'")])
    result = SqlDeltaApplicator().apply(sql, d)
    assert "WHERE [BranchName] = 'Ankara'" in result
    assert result.index("WHERE") < result.index("ORDER BY")


def test_add_filter_inserts_before_order_by():
    d = _delta(add_filters=[FilterDelta(column="BranchName", operator="=", value="'İzmir'")])
    result = SqlDeltaApplicator().apply(BASE_SQL, d)
    assert result.index("[BranchName] = 'İzmir'") < result.index("ORDER BY")


def test_remove_filter_middle_condition():
    sql = "SELECT TOP 5 * FROM T WHERE [A] = '1' AND [B] = '2' AND [C] = '3'"
    result = SqlDeltaApplicator().apply(sql, _delta(remove_filter_columns=["B"]))
    assert "[B]" not in result
    assert "[A] = '1'" in result
    assert "[C] = '3'" in result


def test_remove_filter_first_condition():
    sql = (
        "SELECT * FROM T "
        "WHERE [CategoryName] = 'Kahve' AND [BranchName] = 'Ankara' "
        "ORDER BY x"
    )
    result = SqlDeltaApplicator().apply(sql, _delta(remove_filter_columns=["CategoryName"]))
    assert "[CategoryName]" not in result
    assert "[BranchName] = 'Ankara'" in result


def test_remove_filter_only_condition_removes_where():
    sql = "SELECT * FROM T WHERE [CategoryName] = 'Kahve' ORDER BY x"
    result = SqlDeltaApplicator().apply(sql, _delta(remove_filter_columns=["CategoryName"]))
    assert "WHERE" not in result
    assert "ORDER BY" in result


def test_change_limit():
    result = SqlDeltaApplicator().apply(BASE_SQL, _delta(change_limit=50))
    assert "TOP 50" in result
    assert "TOP 10" not in result


def test_change_orderby():
    result = SqlDeltaApplicator().apply(BASE_SQL, _delta(change_orderby="Total ASC"))
    assert "ORDER BY Total ASC" in result
    assert "ORDER BY Total DESC" not in result


def test_change_groupby():
    sql = (
        "SELECT [BranchName], SUM([RowAmount]) FROM T "
        "GROUP BY [BranchName] ORDER BY 1"
    )
    result = SqlDeltaApplicator().apply(
        sql, _delta(change_groupby="[BranchName], [CategoryName]")
    )
    assert "GROUP BY [BranchName], [CategoryName]" in result


def test_change_select_preserves_top_n():
    result = SqlDeltaApplicator().apply(
        BASE_SQL,
        _delta(change_select="DATEPART(month, [DocumentDate]) AS Month, SUM([RowAmount]) AS Total"),
    )
    assert "TOP 10" in result
    assert "DATEPART(month, [DocumentDate]) AS Month" in result
    assert "FROM [MasterReportDocumentTable]" in result


def test_ensure_date_cast_applied_after_add_filter():
    sql = "SELECT * FROM T WHERE [x] = '1'"
    d = _delta(add_filters=[FilterDelta(column="DocumentDate", operator=">=", value="'2024-01-01'")])
    result = SqlDeltaApplicator().apply(sql, d)
    assert "CAST([DocumentDate] AS DATE)" in result
