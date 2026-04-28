"""
Visualization V2 — Data Models

ChartSpec: LLM veya rule-based path'in urettigi chart specification.
Validator'dan gectikten sonra template engine'e gider.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel


class ChartSpec(BaseModel):
    """Chart specification — LLM/rule-based cikti, validator girdisi."""

    needs_graph: bool
    chart_type: Literal[
        "bar_chart", "line_chart", "pie_chart", "scatter_chart",
        "single_value", "simple_list", "table",
        "comparison", "sunburst", "treemap",
        "heatmap", "turkey_map",
    ]

    # Field mapping
    x_field: Optional[str] = None
    y_field: Optional[str] = None
    y_fields: Optional[List[str]] = None
    series_field: Optional[str] = None
    hierarchy_fields: Optional[List[str]] = None

    # Visual control
    title: Optional[str] = None
    orientation: Optional[Literal["v", "h"]] = None
    sort_by: Optional[str] = None
    sort_order: Optional[Literal["asc", "desc"]] = None
    top_n: Optional[int] = None

    reason: str
