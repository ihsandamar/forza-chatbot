# data_visualization/state.py

from typing import TypedDict, List, Optional, Literal, Any, Dict
from enum import Enum


class OutputType(str, Enum):
    """Supported output types"""
    SINGLE_VALUE = "single_value"
    SIMPLE_LIST = "simple_list"
    TABLE = "table"
    BAR_CHART = "bar_chart"
    LINE_CHART = "line_chart"
    PIE_CHART = "pie_chart"
    SCATTER_CHART = "scatter_chart"
    COMPARISON = "comparison"
    KPI_CARDS = "kpi_cards"
    SUNBURST = "sunburst"  # Multi-level hierarchical chart
    TREEMAP = "treemap"  # Multi-level hierarchical chart


class ColumnType(str, Enum):
    TEXT = "text"
    NUMERIC = "numeric"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"


class ColumnRole(str, Enum):
    DIMENSION = "dimension"
    METRIC = "metric"
    TIME = "time"
    IDENTIFIER = "identifier"


class ColumnInfo(TypedDict):
    name: str
    type: ColumnType
    role: ColumnRole
    sample_values: List[Any]
    unique_count: int
    null_count: int
    min_value: Optional[float]
    max_value: Optional[float]


class DataProfile(TypedDict):
    row_count: int
    column_count: int
    columns: List[ColumnInfo]
    dimension_columns: List[str]
    metric_columns: List[str]
    time_column: Optional[str]
    has_time_series: bool
    has_multiple_dimensions: bool
    is_aggregated: bool
    sample_rows: List[Dict[str, Any]]


class VisualizationDecision(TypedDict):
    """LLM'den gelen karar"""
    needs_graph: bool
    output_type: OutputType
    reason: str


class AxisConfig(TypedDict, total=False):
    field: str
    label: str
    type: Literal["category", "value", "time"]
    format: Optional[str]


class ChartOptions(TypedDict, total=False):
    title: Optional[str]
    show_legend: bool
    show_values: bool
    autosize: bool  # Plotly uses 'autosize' not 'responsive'
    orientation: Optional[Literal["vertical", "horizontal"]]
    stacked: Optional[bool]
    smooth: Optional[bool]
    donut: Optional[bool]
    show_percentage: Optional[bool]
    enable_zoom: Optional[bool]
    limit_rows: Optional[int]
    hierarchy: Optional[List[str]]  # For multi-level charts (sunburst, treemap)


class ChartConfig(TypedDict, total=False):
    type: OutputType
    x_axis: Optional[AxisConfig]
    y_axis: Optional[AxisConfig]
    series_field: Optional[str]
    label_field: Optional[str]
    value_field: Optional[str]
    options: ChartOptions


class VisualizationOutput(TypedDict, total=False):
    output_type: OutputType
    needs_graph: bool
    chart_config: Optional[ChartConfig]
    data: List[Dict[str, Any]]
    summary: Optional[str]


class DataVisualizationState(TypedDict, total=False):
    """Main state for visualization graph"""

    # Input
    user_query: str
    query_intent: Optional[str]
    raw_data: List[Dict[str, Any]]

    # Text2SQL passthrough fields (for state transformation)
    sql_queries: Optional[List[str]]
    results: Optional[List[Dict[str, Any]]]
    parsed_intent: Optional[Any]

    # Analysis (Node 1 - No LLM)
    data_profile: Optional[DataProfile]

    # Decision (Node 2 - LLM)
    viz_decision: Optional[VisualizationDecision]

    # Configuration (Node 3 - No LLM)
    chart_config: Optional[ChartConfig]

    # Plotly Code Generation (Node 4 - LLM)
    plotly_code: Optional[str]
    plotly_figure: Optional[Dict[str, Any]]
    plotly_html_snippet: Optional[str]  # Embeddable HTML snippet

    # Output (Node 6 - No LLM)
    visualization_output: Optional[VisualizationOutput]

    # Error
    error: Optional[str]