"""Tests for comparison_dimension validation in sql_generator_node."""
import pytest


class TestComparisonDimensionSanitization:
    """Validate that comma-separated comparison_dimension is handled safely."""

    def test_single_column_unchanged(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension("CategoryName", {})
        assert comp_dim == "CategoryName"
        assert extra_dims == []

    def test_comma_separated_splits_to_first(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension("CategoryName,ProductName", {})
        assert comp_dim == "CategoryName"
        assert extra_dims == ["ProductName"]

    def test_comma_separated_with_spaces(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension("CategoryName, ProductName", {})
        assert comp_dim == "CategoryName"
        assert extra_dims == ["ProductName"]

    def test_three_columns_comma_separated(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension("CategoryName,ProductName,BranchName", {})
        assert comp_dim == "CategoryName"
        assert extra_dims == ["ProductName", "BranchName"]

    def test_none_returns_none(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension(None, {})
        assert comp_dim is None
        assert extra_dims == []

    def test_empty_string_returns_none(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension("", {})
        assert comp_dim is None
        assert extra_dims == []

    def test_column_with_brackets_stripped(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension("[CategoryName]", {})
        assert comp_dim == "CategoryName"
        assert extra_dims == []

    def test_validates_against_column_metadata(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        metadata = {"CategoryName": "Kategori", "ProductName": "Ürün", "BranchName": "Şube"}
        comp_dim, _ = _sanitize_comparison_dimension("CategoryName", metadata)
        assert comp_dim == "CategoryName"
        comp_dim, _ = _sanitize_comparison_dimension("FakeColumn", metadata)
        assert comp_dim is None


class TestGroupByIntegration:
    def test_extra_dims_added_to_group_by(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        comp_dim, extra_dims = _sanitize_comparison_dimension("CategoryName,ProductName", {})
        group_by = []
        if comp_dim:
            group_by.append(comp_dim)
        group_by.extend(extra_dims)
        group_by.append("CONCAT(YEAR(DocumentDate), '-W', ...)")
        assert group_by == ["CategoryName", "ProductName", "CONCAT(YEAR(DocumentDate), '-W', ...)"]


class TestVisualizationPropagation:
    def test_sanitized_value_propagated_not_raw(self):
        from src.graphs.report_agent.subagents.text2sql.nodes import _sanitize_comparison_dimension
        raw = "CategoryName,ProductName"
        comp_dim, extra_dims = _sanitize_comparison_dimension(raw, {})
        result = {"comparison_dimension": comp_dim}
        assert result["comparison_dimension"] == "CategoryName"
        assert "," not in result["comparison_dimension"]
