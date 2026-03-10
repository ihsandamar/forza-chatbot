"""
Visualization V2 — ChartSpec Validator

Pure Python, LLM yok. 5 kural sirayla calisir:
1. Kolon varlik kontrolu (fuzzy match results kolonlarina karsi)
2. Rol uyumu (x=dimension, y=metric; ters ise swap)
3. Chart-data uyumu (pie+30 kategori, line+zaman yok, vb.)
4. Eksik field tamamlama (profile'dan doldur)
5. Multi-metric dogrulama (y_fields gecerli mi?)
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def validate_spec(
    spec: dict,
    results: List[Dict[str, Any]],
    profile: dict,
) -> dict:
    """
    Validate and fix ChartSpec dict against actual data.

    Args:
        spec: ChartSpec.model_dump() or rule-based dict
        results: SQL query results (actual column names)
        profile: DataProfile dict

    Returns:
        Validated/fixed spec dict (same structure)
    """
    spec = dict(spec)  # copy
    if not results:
        return spec

    actual_columns = list(results[0].keys())
    dimension_cols = profile.get("dimension_columns", [])
    metric_cols = profile.get("metric_columns", [])
    time_col = profile.get("time_column")
    columns_info = {c["name"]: c for c in profile.get("columns", [])}

    # Rule 1: Column existence
    for field_name in ("x_field", "y_field", "series_field"):
        value = spec.get(field_name)
        if value and value not in actual_columns:
            resolved = _fuzzy_resolve(value, actual_columns)
            if resolved:
                logger.info(f"[VALIDATOR] Rule 1: '{value}' -> '{resolved}'")
            else:
                logger.warning(f"[VALIDATOR] Rule 1: '{value}' not found, cleared")
            spec[field_name] = resolved

    # Rule 2: Role conformity (swap if x=metric and y=dimension)
    x = spec.get("x_field")
    y = spec.get("y_field")
    if x and y:
        x_info = columns_info.get(x, {})
        y_info = columns_info.get(y, {})
        x_is_metric = x_info.get("role") == "metric" or x in metric_cols
        y_is_dim = y_info.get("role") == "dimension" or y in dimension_cols
        if x_is_metric and y_is_dim:
            spec["x_field"], spec["y_field"] = y, x
            logger.info(f"[VALIDATOR] Rule 2: Swapped x/y ({x} <-> {y})")

    # Rule 3: Chart-data compatibility
    chart_type = spec.get("chart_type")

    if chart_type == "pie_chart":
        x_val = spec.get("x_field")
        if x_val and x_val in actual_columns:
            unique_count = len(set(row.get(x_val) for row in results))
            if unique_count > 15 and not spec.get("top_n"):
                spec["top_n"] = 10
                logger.info(f"[VALIDATOR] Rule 3: pie_chart {unique_count} categories -> top_n=10")

    if chart_type == "line_chart":
        x_val = spec.get("x_field")
        is_time = (
            time_col is not None
            or (x_val and columns_info.get(x_val, {}).get("role") == "time")
        )
        if not is_time:
            spec["chart_type"] = "bar_chart"
            logger.info("[VALIDATOR] Rule 3: line_chart without time -> bar_chart")

    if chart_type == "scatter_chart":
        if len(metric_cols) < 2 and not spec.get("y_fields"):
            spec["chart_type"] = "bar_chart"
            logger.info("[VALIDATOR] Rule 3: scatter with <2 metrics -> bar_chart")

    # Rule 4: Missing field completion
    if spec.get("needs_graph") and not spec.get("x_field"):
        spec["x_field"] = time_col or (dimension_cols[0] if dimension_cols else None)
        if spec["x_field"]:
            logger.info(f"[VALIDATOR] Rule 4: x_field filled -> '{spec['x_field']}'")

    if spec.get("needs_graph") and not spec.get("y_field") and not spec.get("y_fields"):
        spec["y_field"] = metric_cols[0] if metric_cols else None
        if spec["y_field"]:
            logger.info(f"[VALIDATOR] Rule 4: y_field filled -> '{spec['y_field']}'")

    if spec.get("needs_graph") and (not spec.get("x_field") or not spec.get("y_field")):
        if not spec.get("y_fields"):
            spec["needs_graph"] = False
            spec["chart_type"] = "table"
            logger.warning("[VALIDATOR] Rule 4: Cannot determine axes -> table fallback")

    # Rule 5: Multi-metric validation
    y_fields = spec.get("y_fields")
    if y_fields:
        valid = [f for f in y_fields if f in actual_columns]
        if len(valid) == 0:
            spec["y_fields"] = None
            logger.warning("[VALIDATOR] Rule 5: No valid y_fields, cleared")
        elif len(valid) == 1:
            spec["y_field"] = valid[0]
            spec["y_fields"] = None
            logger.info(f"[VALIDATOR] Rule 5: Single y_field '{valid[0]}', moved to y_field")
        else:
            spec["y_fields"] = valid

    return spec


def _fuzzy_resolve(value: str, actual_columns: List[str]) -> Optional[str]:
    """Fuzzy match a field name against actual result columns."""
    # Exact case-insensitive
    lower_map = {c.lower(): c for c in actual_columns}
    if value.lower() in lower_map:
        return lower_map[value.lower()]

    # Underscore/space normalized
    normalized = value.replace("_", "").replace(" ", "").lower()
    for col in actual_columns:
        if col.replace("_", "").replace(" ", "").lower() == normalized:
            return col

    # Fuzzy match
    try:
        from rapidfuzz import process
        match = process.extractOne(value, actual_columns, score_cutoff=80)
        return match[0] if match else None
    except ImportError:
        return None
