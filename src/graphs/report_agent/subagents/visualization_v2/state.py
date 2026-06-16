"""
Visualization V2 — State Definition

VisualizationState: LangGraph shared-state pattern ile parent ReportState'e baglanir.
v2, v1'e göre şu 4 ek field içerir: messages, time_granularity, comparison_dimension, requested_chart_type.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# =============================================================================
# COLUMN TYPES & ROLES  (DataAnalyzer tarafından kullanılır)
# =============================================================================

class ColumnType(str, Enum):
    TEXT = "text"
    NUMERIC = "numeric"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    UNKNOWN = "unknown"


class ColumnRole(str, Enum):
    DIMENSION = "dimension"
    METRIC = "metric"
    TIME = "time"
    IDENTIFIER = "identifier"


class ColumnInfo(TypedDict, total=False):
    name: str
    type: ColumnType
    role: ColumnRole
    sample_values: List[Any]
    unique_count: int
    null_count: int
    min_value: Optional[float]
    max_value: Optional[float]
    avg_value: Optional[float]


class DataProfile(TypedDict, total=False):
    row_count: int
    column_count: int
    columns: List[ColumnInfo]
    dimension_columns: List[str]
    metric_columns: List[str]
    time_column: Optional[str]
    time_columns: Optional[List[str]]
    has_time_series: bool
    has_multiple_dimensions: bool
    is_aggregated: bool
    sample_rows: List[Dict[str, Any]]


# =============================================================================
# VISUALIZATION STATE
# =============================================================================

class VisualizationState(TypedDict, total=False):
    # --- ReportState overlapping (auto-sync) ---
    messages: Optional[list]               # conversation context (LLM prompt'a eklenir)
    results: Optional[List[Dict[str, Any]]]
    user_query: str
    viz_request: Optional[str]
    query_type: Optional[str]
    wants_visualization: Optional[bool]
    visualization_output: Optional[Dict[str, Any]]
    error: Optional[str]
    time_granularity: Optional[str]       # from text2sql, for chart type decision
    comparison_dimension: Optional[str]   # from text2sql, entity column for multi-dim charts
    requested_chart_type: Optional[str]   # from intent classification
    chart_x_hint: Optional[str]           # x-axis kolon ipucu — classify_intent'ten gelir

    # --- Internal ---
    data_profile: Optional[DataProfile]   # typed — DataProfile defined above
    viz_decision: Optional[Dict[str, Any]]  # ChartSpec.model_dump()
    plotly_html_snippet: Optional[str]
    summary_html_snippet: Optional[str]   # compact sparkline for inline chat display
