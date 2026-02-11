"""
Query Type Visualization Mapping

Her query type için en uygun görselleştirme türü ve konfigürasyonu.
Bu mapping'ler decide_visualization_node tarafından kullanılır.

Phase 2: Visualization Decision Enhancement
"""

from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# QUERY TYPE VISUALIZATION MAPPING
# =============================================================================

QUERY_TYPE_VIZ_MAPPING = {
    "ranking": {
        "primary_chart": "bar_chart",
        "alternatives": ["table", "simple_list"],
        "reasoning": "Horizontal bar chart best for rankings (easy to read labels)",
        "needs_graph": True,
        "chart_config": {
            "orientation": "horizontal",
            "sort_by": "value",
            "order": "desc",
            "show_values": True,
            "color_scheme": "sequential"
        },
        "examples": [
            "En çok satan 10 ürün",
            "En az ciro yapan 5 şube",
            "Top 3 müşteri"
        ]
    },

    "comparison": {
        "primary_chart": "bar_chart",
        "alternatives": ["table", "line_chart"],
        "reasoning": "Grouped bars for side-by-side comparison",
        "needs_graph": True,
        "chart_config": {
            "orientation": "vertical",
            "group_by": "entity",
            "show_legend": True,
            "color_scheme": "categorical"
        },
        "examples": [
            "İstanbul vs Ankara satışları",
            "Ürün A ile Ürün B karşılaştırması"
        ]
    },

    "time_series": {
        "primary_chart": "line_chart",
        "alternatives": ["bar_chart", "table"],
        "reasoning": "Line chart shows temporal trends clearly",
        "needs_graph": True,
        "chart_config": {
            "x_axis": "date",
            "y_axis": "metric",
            "show_points": False,
            "smooth": True,
            "fill_area": False
        },
        "examples": [
            "Son 6 aydaki satışlar",
            "Bu yılki aylık ciro",
            "Son 30 günün günlük trendi"
        ]
    },

    "time_series_comparison": {
        "primary_chart": "line_chart",
        "alternatives": ["bar_chart", "table"],
        "reasoning": "Multiple lines for comparing trends across entities",
        "needs_graph": True,
        "chart_config": {
            "x_axis": "date",
            "y_axis": "metric",
            "group_by": "entity",
            "show_legend": True,
            "show_points": False,
            "color_scheme": "categorical"
        },
        "examples": [
            "Ürün A ve B'nin son 3 aydaki satış trendi",
            "İstanbul ve Ankara'nın aylık ciro karşılaştırması"
        ]
    },

    "single_value": {
        "primary_chart": "metric_card",
        "alternatives": ["simple_list"],
        "reasoning": "Single number display (KPI card)",
        "needs_graph": False,
        "chart_config": {
            "format": "number",
            "show_trend": False,
            "large_display": True
        },
        "examples": [
            "Toplam ciro nedir?",
            "Ortalama sipariş tutarı",
            "Kaç müşterimiz var?"
        ]
    },

    "aggregation": {
        "primary_chart": "bar_chart",
        "alternatives": ["table", "pie_chart"],
        "reasoning": "Bar chart for category comparisons",
        "needs_graph": True,
        "chart_config": {
            "orientation": "vertical",
            "sort_by": "value",
            "order": "desc",
            "show_values": True
        },
        "examples": [
            "Kategorilere göre satış toplamı",
            "Şubelere göre ortalama ciro"
        ]
    },

    "distribution": {
        "primary_chart": "pie_chart",
        "alternatives": ["bar_chart", "table"],
        "reasoning": "Pie chart shows proportions clearly",
        "needs_graph": True,
        "chart_config": {
            "show_percentage": True,
            "show_legend": True,
            "min_slice_percentage": 2,  # Hide slices < 2%
            "max_slices": 10  # Combine small slices into "Other"
        },
        "examples": [
            "Satışların şubelere göre dağılımı",
            "Ürün kategorilerinin oranı"
        ]
    },

    "trend": {
        "primary_chart": "line_chart",
        "alternatives": ["bar_chart", "table"],
        "reasoning": "Line chart with trend indicators",
        "needs_graph": True,
        "chart_config": {
            "show_trend_line": True,
            "show_change_percentage": True,
            "highlight_changes": True,
            "fill_area": True,
            "area_opacity": 0.3
        },
        "examples": [
            "Satışlar artıyor mu?",
            "Geçen aya göre değişim",
            "Yıllık büyüme trendi"
        ]
    },

    # Default/fallback için
    "default": {
        "primary_chart": "table",
        "alternatives": ["simple_list"],
        "reasoning": "Default table view when query type unknown",
        "needs_graph": False,
        "chart_config": {},
        "examples": []
    }
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_viz_config(query_type: str) -> Dict[str, Any]:
    """
    Get visualization configuration for query_type.

    Args:
        query_type: Query type identifier

    Returns:
        Visualization config dict
    """
    viz_config = QUERY_TYPE_VIZ_MAPPING.get(query_type)

    if not viz_config:
        logger.warning(f"[VIZ_MAPPING] Unknown query_type: {query_type}, using default")
        return QUERY_TYPE_VIZ_MAPPING["default"]

    return viz_config


def get_chart_type(query_type: str) -> str:
    """
    Get primary chart type for query_type.

    Args:
        query_type: Query type identifier

    Returns:
        Chart type string (e.g., "bar_chart", "line_chart")
    """
    viz_config = get_viz_config(query_type)
    return viz_config.get("primary_chart", "table")


def should_show_graph(query_type: str) -> bool:
    """
    Check if query_type should show a graph.

    Args:
        query_type: Query type identifier

    Returns:
        True if graph should be shown
    """
    viz_config = get_viz_config(query_type)
    return viz_config.get("needs_graph", False)


def get_chart_alternatives(query_type: str) -> List[str]:
    """
    Get alternative chart types for query_type.

    Args:
        query_type: Query type identifier

    Returns:
        List of alternative chart types
    """
    viz_config = get_viz_config(query_type)
    return viz_config.get("alternatives", ["table"])


def format_viz_decision(
    query_type: str,
    override_chart_type: str = None,
    data_shape: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Format visualization decision for state.

    Args:
        query_type: Query type identifier
        override_chart_type: Optional override for chart type (user request)
        data_shape: Optional data shape analysis for additional context

    Returns:
        Formatted viz_decision dict for state
    """
    viz_config = get_viz_config(query_type)

    # Use override if provided, otherwise use primary chart
    chart_type = override_chart_type or viz_config["primary_chart"]
    needs_graph = override_chart_type is not None or viz_config.get("needs_graph", False)

    decision = {
        "needs_graph": needs_graph,
        "output_type": chart_type,
        "chart_type": chart_type,
        "reasoning": viz_config.get("reasoning", "Query type based visualization"),
        "query_type_driven": True,
        "query_type": query_type,
        "alternatives": viz_config.get("alternatives", []),
        "chart_config": viz_config.get("chart_config", {})
    }

    # Add data shape info if provided
    if data_shape:
        decision["data_shape"] = data_shape

    logger.info(f"[VIZ_DECISION] {query_type} → {chart_type} (needs_graph={needs_graph})")

    return decision


def analyze_data_shape(results: List[Dict]) -> Dict[str, Any]:
    """
    Analyze data shape for fallback visualization decision.

    Used when query_type is not available.

    Args:
        results: Query results

    Returns:
        Data shape analysis dict
    """
    if not results or len(results) == 0:
        return {
            "row_count": 0,
            "column_count": 0,
            "is_single_value": False,
            "is_time_series": False,
            "numeric_columns": [],
            "text_columns": []
        }

    row_count = len(results)
    first_row = results[0]
    column_count = len(first_row.keys())

    # Check for single value
    is_single_value = row_count == 1 and column_count == 1

    # Detect column types
    numeric_columns = []
    text_columns = []
    date_columns = []

    for key, value in first_row.items():
        if isinstance(value, (int, float)):
            numeric_columns.append(key)
        elif isinstance(value, str):
            # Check if it's a date-like string
            if any(kw in key.lower() for kw in ["date", "time", "day", "month", "year", "tarih", "gun", "ay", "yil"]):
                date_columns.append(key)
            else:
                text_columns.append(key)

    is_time_series = len(date_columns) > 0

    return {
        "row_count": row_count,
        "column_count": column_count,
        "is_single_value": is_single_value,
        "is_time_series": is_time_series,
        "numeric_columns": numeric_columns,
        "text_columns": text_columns,
        "date_columns": date_columns
    }


__all__ = [
    "QUERY_TYPE_VIZ_MAPPING",
    "get_viz_config",
    "get_chart_type",
    "should_show_graph",
    "get_chart_alternatives",
    "format_viz_decision",
    "analyze_data_shape"
]
