"""Tests for explicit chart type detection from user query."""
import pytest


class TestDetectExplicitChartType:
    """_detect_explicit_chart_type should extract chart type from Turkish/English queries."""

    def _detect(self, query: str):
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _detect_explicit_chart_type
        return _detect_explicit_chart_type(query)

    # --- Heatmap ---
    def test_heatmap_turkish(self):
        assert self._detect("satislari heatmap grafik olarak goster") == "heatmap"

    def test_isi_haritasi(self):
        assert self._detect("kategorilerin isi haritasi") == "heatmap"

    def test_isı_haritası_with_special_chars(self):
        assert self._detect("ısı haritası olarak göster") == "heatmap"

    # --- Pie ---
    def test_pasta_grafik(self):
        assert self._detect("pasta grafik ver") == "pie_chart"

    def test_pie_chart_english(self):
        assert self._detect("show as pie chart") == "pie_chart"

    # --- Bar ---
    def test_bar_grafik(self):
        assert self._detect("bar grafik olarak goster") == "bar_chart"

    def test_cubuk_grafik(self):
        assert self._detect("cubuk grafik ver") == "bar_chart"

    def test_çubuk_grafik(self):
        assert self._detect("çubuk grafik göster") == "bar_chart"

    # --- Line ---
    def test_cizgi_grafik(self):
        assert self._detect("cizgi grafik ile goster") == "line_chart"

    def test_çizgi_grafik(self):
        assert self._detect("çizgi grafik olarak göster") == "line_chart"

    def test_line_chart_english(self):
        assert self._detect("show as line chart") == "line_chart"

    def test_trend_grafik(self):
        assert self._detect("trend grafigi goster") == "line_chart"

    # --- Scatter ---
    def test_scatter_english(self):
        assert self._detect("scatter plot goster") == "scatter_chart"

    def test_dagilim_grafigi(self):
        assert self._detect("dagilim grafigi ver") == "scatter_chart"

    # --- Sunburst ---
    def test_sunburst(self):
        assert self._detect("sunburst grafik ver") == "sunburst"

    # --- Treemap ---
    def test_treemap(self):
        assert self._detect("treemap olarak goster") == "treemap"

    # --- No match ---
    def test_no_explicit_type(self):
        assert self._detect("son 3 aydaki satislari goster") is None

    def test_empty_query(self):
        assert self._detect("") is None

    def test_generic_grafik_no_type(self):
        """'grafik ver' alone should NOT match any specific type."""
        assert self._detect("grafik ver") is None

    def test_case_insensitive(self):
        assert self._detect("HEATMAP grafik ver") == "heatmap"

    def test_partial_word_no_match(self):
        """'barcin' should not match 'bar'."""
        assert self._detect("barcin satis raporu") is None


class TestExplicitChartTypeOverride:
    """viz_decider should use explicit chart type when user requests one."""

    def test_rule_based_overridden_by_explicit_heatmap(self):
        """TIME_SERIES_COMPARISON normally -> line_chart, but user says heatmap -> heatmap."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "dimension_columns": ["CategoryName", "Ay"],
            "metric_columns": ["ToplamCiro"],
            "time_column": "Ay",
            "row_count": 49,
        }
        # Without explicit -> line_chart (existing behavior)
        result = _rule_based_decision(
            "TIME_SERIES_COMPARISON", True, profile,
            time_granularity="monthly", comparison_dimension="CategoryName",
        )
        assert result["chart_type"] == "line_chart"

        # With explicit -> heatmap
        result = _rule_based_decision(
            "TIME_SERIES_COMPARISON", True, profile,
            time_granularity="monthly", comparison_dimension="CategoryName",
            explicit_chart_type="heatmap",
        )
        assert result["chart_type"] == "heatmap"

    def test_explicit_pie_overrides_bar(self):
        """RANKING normally -> bar_chart, but user says pie -> pie_chart."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "dimension_columns": ["BranchName"],
            "metric_columns": ["RowAmount"],
            "time_column": None,
            "row_count": 5,
        }
        result = _rule_based_decision(
            "RANKING", True, profile,
            explicit_chart_type="pie_chart",
        )
        assert result["chart_type"] == "pie_chart"

    def test_explicit_none_preserves_default(self):
        """No explicit type -> default rule-based behavior unchanged."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "dimension_columns": ["BranchName"],
            "metric_columns": ["RowAmount"],
            "time_column": None,
            "row_count": 5,
        }
        result = _rule_based_decision(
            "RANKING", True, profile,
            explicit_chart_type=None,
        )
        assert result["chart_type"] == "bar_chart"

    def test_explicit_heatmap_sets_series_field(self):
        """Heatmap with comparison_dimension should set series_field."""
        from src.graphs.report_agent.subagents.visualization_v2.nodes import _rule_based_decision
        profile = {
            "dimension_columns": ["CategoryName", "Ay"],
            "metric_columns": ["ToplamCiro"],
            "time_column": "Ay",
            "row_count": 49,
        }
        result = _rule_based_decision(
            "TIME_SERIES_COMPARISON", True, profile,
            time_granularity="monthly", comparison_dimension="CategoryName",
            explicit_chart_type="heatmap",
        )
        assert result["series_field"] == "CategoryName"
