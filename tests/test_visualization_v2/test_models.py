"""ChartSpec model validation tests."""
import pytest
from pydantic import ValidationError


def test_chartspec_valid_bar():
    from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
    spec = ChartSpec(
        needs_graph=True,
        chart_type="bar_chart",
        x_field="BranchName",
        y_field="RowAmount",
        reason="Bar chart for branch comparison",
    )
    assert spec.chart_type == "bar_chart"
    assert spec.x_field == "BranchName"
    assert spec.orientation is None


def test_chartspec_valid_multi_metric():
    from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
    spec = ChartSpec(
        needs_graph=True,
        chart_type="bar_chart",
        x_field="BranchName",
        y_fields=["RowAmount", "Quantity"],
        reason="Multi metric bar",
    )
    assert spec.y_fields == ["RowAmount", "Quantity"]
    assert spec.y_field is None


def test_chartspec_valid_no_graph():
    from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
    spec = ChartSpec(
        needs_graph=False,
        chart_type="table",
        reason="Table display",
    )
    assert spec.needs_graph is False
    assert spec.x_field is None


def test_chartspec_invalid_chart_type():
    from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
    with pytest.raises(ValidationError):
        ChartSpec(
            needs_graph=True,
            chart_type="invalid_type",
            reason="should fail",
        )


def test_chartspec_hierarchy_fields():
    from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
    spec = ChartSpec(
        needs_graph=True,
        chart_type="sunburst",
        hierarchy_fields=["CategoryName", "ProductName"],
        y_field="RowAmount",
        reason="Sunburst hierarchy",
    )
    assert spec.hierarchy_fields == ["CategoryName", "ProductName"]


def test_chartspec_sort_and_topn():
    from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
    spec = ChartSpec(
        needs_graph=True,
        chart_type="bar_chart",
        x_field="ProductName",
        y_field="RowAmount",
        sort_by="RowAmount",
        sort_order="desc",
        top_n=10,
        reason="Top 10 products",
    )
    assert spec.sort_order == "desc"
    assert spec.top_n == 10
