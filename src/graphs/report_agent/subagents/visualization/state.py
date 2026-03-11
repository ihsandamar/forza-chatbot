from enum import Enum
from typing import Any, Dict, List, Literal, Optional, TypedDict


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
    """
    Visualization subagent state.

    Overlapping keys (LangGraph otomatik parent ReportState ile sync eder):
        results, user_query, query_type, visualization_output, error

    Internal keys (sadece bu subgraph içinde kalır):
        data_profile, viz_decision, plotly_html_snippet
    """

    # --- ReportState overlapping ---
    results: Optional[List[Dict[str, Any]]]
    user_query: str                       # SQL semantic query (SQL node'lar için)
    viz_request: Optional[str]           # Görselleştirme tarzı ("pasta grafik" vb.) — sadece revisualize'da
    query_type: Optional[str]
    wants_visualization: Optional[bool]   # Kullanıcı grafik istedi mi? (ReportState'ten sync)
    visualization_output: Optional[Dict[str, Any]]
    error: Optional[str]

    # --- Internal ---
    data_profile: Optional[DataProfile]
    viz_decision: Optional[Dict[str, Any]]   # VizDecision.model_dump()
    plotly_html_snippet: Optional[str]
