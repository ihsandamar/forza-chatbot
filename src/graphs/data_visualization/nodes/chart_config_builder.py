# data_visualization/nodes/chart_config_builder.py

from typing import Dict, Any, Optional
from ..state import (
    DataVisualizationState,
    ChartConfig,
    AxisConfig,
    ChartOptions,
    OutputType,
    DataProfile
)


class ChartConfigBuilder:
    """
    Builds chart configuration based on output type and data profile.
    No LLM - pure rule-based logic.
    """
    
    # Default row limits
    MAX_PIE_SLICES = 8
    MAX_BAR_ITEMS = 20
    MAX_LINE_POINTS = 100
    
    def build(self, state: DataVisualizationState) -> DataVisualizationState:
        """Build chart configuration"""
        
        viz_decision = state.get("viz_decision")
        data_profile = state.get("data_profile")
        user_query = state.get("user_query", "")
        raw_data = state.get("raw_data", [])
        
        if not viz_decision:
            return {**state, "chart_config": None}
        
        output_type = viz_decision["output_type"]
        
        # Non-chart types - minimal config
        if output_type in [OutputType.SINGLE_VALUE, OutputType.SIMPLE_LIST, OutputType.TABLE]:
            chart_config = self._build_non_chart_config(output_type, data_profile)
        
        # Chart types
        elif output_type == OutputType.BAR_CHART:
            chart_config = self._build_bar_config(data_profile, user_query)
        
        elif output_type == OutputType.LINE_CHART:
            chart_config = self._build_line_config(data_profile, user_query)
        
        elif output_type == OutputType.PIE_CHART:
            chart_config = self._build_pie_config(data_profile, user_query)
        
        elif output_type == OutputType.SCATTER_CHART:
            chart_config = self._build_scatter_config(data_profile, user_query)
        
        elif output_type == OutputType.COMPARISON:
            chart_config = self._build_comparison_config(data_profile, user_query)

        elif output_type == OutputType.SUNBURST:
            chart_config = self._build_sunburst_config(data_profile, user_query)

        elif output_type == OutputType.TREEMAP:
            chart_config = self._build_treemap_config(data_profile, user_query)

        else:
            chart_config = self._build_table_config(data_profile)

        return {**state, "chart_config": chart_config}
    
    def _build_non_chart_config(self, output_type: OutputType, profile: DataProfile) -> ChartConfig:
        """Config for non-chart outputs"""
        return ChartConfig(
            type=output_type,
            options=ChartOptions(
                title=None,
                show_legend=False,
                show_values=True,
                autosize=True
            )
        )
    
    def _build_bar_config(self, profile: DataProfile, query: str) -> ChartConfig:
        """Build bar chart configuration"""
        
        # X-axis: first dimension column
        x_field = profile["dimension_columns"][0] if profile["dimension_columns"] else None
        
        # Y-axis: first metric column
        y_field = profile["metric_columns"][0] if profile["metric_columns"] else None
        
        # Series: second dimension (if exists)
        series_field = None
        if len(profile["dimension_columns"]) > 1:
            series_field = profile["dimension_columns"][1]
        
        return ChartConfig(
            type=OutputType.BAR_CHART,
            x_axis=AxisConfig(
                field=x_field,
                label=self._humanize_column_name(x_field),
                type="category"
            ) if x_field else None,
            y_axis=AxisConfig(
                field=y_field,
                label=self._humanize_column_name(y_field),
                type="value",
                format=self._detect_format(y_field)
            ) if y_field else None,
            series_field=series_field,
            options=ChartOptions(
                title=self._generate_title(query, "bar"),
                show_legend=series_field is not None,
                show_values=True,
                autosize=True,
                orientation="vertical",
                limit_rows=self.MAX_BAR_ITEMS
            )
        )
    
    def _build_line_config(self, profile: DataProfile, query: str) -> ChartConfig:
        """Build line chart configuration"""
        
        # X-axis: time column or first dimension
        x_field = profile["time_column"] or (
            profile["dimension_columns"][0] if profile["dimension_columns"] else None
        )
        
        # Y-axis: first metric
        y_field = profile["metric_columns"][0] if profile["metric_columns"] else None
        
        # Series: dimension column (if time is x-axis)
        series_field = None
        if profile["time_column"] and profile["dimension_columns"]:
            series_field = profile["dimension_columns"][0]
        
        return ChartConfig(
            type=OutputType.LINE_CHART,
            x_axis=AxisConfig(
                field=x_field,
                label=self._humanize_column_name(x_field),
                type="time" if profile["time_column"] else "category"
            ) if x_field else None,
            y_axis=AxisConfig(
                field=y_field,
                label=self._humanize_column_name(y_field),
                type="value",
                format=self._detect_format(y_field)
            ) if y_field else None,
            series_field=series_field,
            options=ChartOptions(
                title=self._generate_title(query, "line"),
                show_legend=series_field is not None,
                show_values=False,
                autosize=True,
                smooth=True,
                enable_zoom=True,
                limit_rows=self.MAX_LINE_POINTS
            )
        )
    
    def _build_pie_config(self, profile: DataProfile, query: str) -> ChartConfig:
        """Build pie chart configuration"""
        
        # Label: first dimension
        label_field = profile["dimension_columns"][0] if profile["dimension_columns"] else None
        
        # Value: first metric
        value_field = profile["metric_columns"][0] if profile["metric_columns"] else None
        
        return ChartConfig(
            type=OutputType.PIE_CHART,
            label_field=label_field,
            value_field=value_field,
            options=ChartOptions(
                title=self._generate_title(query, "pie"),
                show_legend=True,
                show_values=True,
                show_percentage=True,
                donut=False,
                autosize=True,
                limit_rows=self.MAX_PIE_SLICES
            )
        )
    
    def _build_scatter_config(self, profile: DataProfile, query: str) -> ChartConfig:
        """Build scatter chart configuration"""
        
        metrics = profile["metric_columns"]
        
        # X and Y: first two metrics
        x_field = metrics[0] if len(metrics) > 0 else None
        y_field = metrics[1] if len(metrics) > 1 else metrics[0] if metrics else None
        
        # Series: first dimension
        series_field = profile["dimension_columns"][0] if profile["dimension_columns"] else None
        
        return ChartConfig(
            type=OutputType.SCATTER_CHART,
            x_axis=AxisConfig(
                field=x_field,
                label=self._humanize_column_name(x_field),
                type="value"
            ) if x_field else None,
            y_axis=AxisConfig(
                field=y_field,
                label=self._humanize_column_name(y_field),
                type="value"
            ) if y_field else None,
            series_field=series_field,
            options=ChartOptions(
                title=self._generate_title(query, "scatter"),
                show_legend=series_field is not None,
                autosize=True,
                enable_zoom=True
            )
        )
    
    def _build_comparison_config(self, profile: DataProfile, query: str) -> ChartConfig:
        """Build comparison configuration"""
        return ChartConfig(
            type=OutputType.COMPARISON,
            options=ChartOptions(
                title=self._generate_title(query, "comparison"),
                show_values=True,
                autosize=True
            )
        )

    def _build_sunburst_config(self, profile: DataProfile, query: str) -> ChartConfig:
        """Build sunburst chart configuration for multi-level grouping"""

        # Sunburst uses multiple dimensions as hierarchy levels
        # Value: first metric column
        value_field = profile["metric_columns"][0] if profile["metric_columns"] else None

        # Build hierarchy from time column + dimension columns (up to 3 levels for readability)
        hierarchy_fields = []

        # Add time column first if exists (for temporal grouping)
        if profile["time_column"]:
            hierarchy_fields.append(profile["time_column"])

        # Add dimension columns
        remaining_slots = 3 - len(hierarchy_fields)
        if profile["dimension_columns"] and remaining_slots > 0:
            hierarchy_fields.extend(profile["dimension_columns"][:remaining_slots])

        return ChartConfig(
            type=OutputType.SUNBURST,
            label_field=None,  # Sunburst uses path/hierarchy
            value_field=value_field,
            series_field=None,  # Not applicable for sunburst
            options=ChartOptions(
                title=self._generate_title(query, "sunburst"),
                show_legend=False,
                show_values=True,
                show_percentage=True,
                autosize=True,
                hierarchy=hierarchy_fields  # Store hierarchy fields in options
            )
        )

    def _build_treemap_config(self, profile: DataProfile, query: str) -> ChartConfig:
        """Build treemap chart configuration for multi-level grouping"""

        # Treemap uses multiple dimensions as hierarchy levels
        # Value: first metric column
        value_field = profile["metric_columns"][0] if profile["metric_columns"] else None

        # Build hierarchy from time column + dimension columns (up to 3 levels for readability)
        hierarchy_fields = []

        # Add time column first if exists (for temporal grouping)
        if profile["time_column"]:
            hierarchy_fields.append(profile["time_column"])

        # Add dimension columns
        remaining_slots = 3 - len(hierarchy_fields)
        if profile["dimension_columns"] and remaining_slots > 0:
            hierarchy_fields.extend(profile["dimension_columns"][:remaining_slots])

        return ChartConfig(
            type=OutputType.TREEMAP,
            label_field=None,  # Treemap uses path/hierarchy
            value_field=value_field,
            series_field=None,  # Not applicable for treemap
            options=ChartOptions(
                title=self._generate_title(query, "treemap"),
                show_legend=False,
                show_values=True,
                show_percentage=True,
                autosize=True,
                hierarchy=hierarchy_fields  # Store hierarchy fields in options
            )
        )

    def _build_table_config(self, profile: DataProfile) -> ChartConfig:
        """Build table configuration"""
        return ChartConfig(
            type=OutputType.TABLE,
            options=ChartOptions(
                show_values=True,
                autosize=True
            )
        )
    
    def _humanize_column_name(self, name: Optional[str]) -> str:
        """Convert column name to human readable"""
        if not name:
            return ""
        # CamelCase to spaces
        import re
        result = re.sub(r'([A-Z])', r' \1', name)
        # Underscores to spaces
        result = result.replace('_', ' ')
        return result.strip().title()
    
    def _detect_format(self, field_name: Optional[str]) -> Optional[str]:
        """Detect value format based on field name"""
        if not field_name:
            return None
        
        field_lower = field_name.lower()
        
        if any(kw in field_lower for kw in ['amount', 'price', 'cost', 'revenue', 'sales', 'tutar', 'ciro', 'fiyat']):
            return "currency_TRY"
        
        if any(kw in field_lower for kw in ['percent', 'rate', 'ratio', 'oran', 'yuzde']):
            return "percentage"
        
        if any(kw in field_lower for kw in ['count', 'qty', 'quantity', 'adet', 'sayi']):
            return "number"
        
        return "number"
    
    def _generate_title(self, query: str, chart_type: str) -> str:
        """Generate simple title from query"""
        # Take first 50 chars of query as title
        title = query[:50]
        if len(query) > 50:
            title += "..."
        return title


def chart_config_builder_node(state: DataVisualizationState) -> Dict[str, Any]:
    """LangGraph node wrapper"""
    builder = ChartConfigBuilder()
    return builder.build(state)