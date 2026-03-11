"""
Visualization V2 — State Definition

VisualizationState: LangGraph shared-state pattern ile parent ReportState'e baglanir.
Mevcut v1 state ile ayni key'ler — parent uyumlu.
"""
from typing import Any, Dict, List, Optional, TypedDict


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

    # --- Internal ---
    data_profile: Optional[Dict[str, Any]]
    viz_decision: Optional[Dict[str, Any]]  # ChartSpec.model_dump()
    plotly_html_snippet: Optional[str]
