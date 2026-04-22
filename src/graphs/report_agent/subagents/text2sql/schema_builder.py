"""
schema_builder.py — deterministic SemanticIntent → QuerySchema conversion.

No LLM involved. Pure Python business logic.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional

from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
from src.graphs.report_agent.subagents.text2sql.exceptions import SchemaBuilderError, SemanticExtractionError
from src.graphs.report_agent.subagents.text2sql.prompts import (
    QuerySchema,
    SchemaAggregation,
    SchemaFilter,
)
from src.graphs.report_agent.subagents.text2sql.semantic_models import (
    SemanticIntent,
    TermMatch,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Aggregation alias helpers
# ---------------------------------------------------------------------------

_METRIC_ALIAS: Dict[str, str] = {
    "RowAmount": "ToplamCiro",
    "Quantity": "ToplamAdet",
}


def _agg_alias(function: str, column: str) -> str:
    if column in _METRIC_ALIAS:
        return _METRIC_ALIAS[column]
    return f"{function}_{column}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_query_schema(
    intent: SemanticIntent,
    term_resolution: Dict[str, TermMatch],
    query_type: str,
    time_breakdown: bool,
    today: Optional[date] = None,
) -> QuerySchema:
    """Convert SemanticIntent + TermMatch map to a QuerySchema deterministically.

    Args:
        intent:          Parsed semantic intent (entities, metrics, time, …).
        term_resolution: Map of raw_text → TermMatch for all recognized terms.
        query_type:      One of SINGLE | LISTING | COMPARISON | TIME_SERIES_COMPARISON | RANKING.
        time_breakdown:  When True, forces time granularity even if SemanticTime.breakdown=False.
        today:           Reference date (defaults to date.today()).

    Returns:
        QuerySchema ready for the sql_query_builder node.

    Raises:
        SchemaBuilderError: Wraps date parsing errors or any other conversion failure.
    """
    if today is None:
        today = date.today()

    filters: List[SchemaFilter] = []
    aggregations: List[SchemaAggregation] = []
    group_by: List[str] = []
    time_granularity: Optional[str] = None
    comparison_dimension: Optional[str] = None

    # ------------------------------------------------------------------
    # 1. Metrics → aggregations
    # ------------------------------------------------------------------
    for metric in intent.metrics:
        tm = term_resolution.get(metric.raw_text)
        col = tm.column_name if tm else None
        if col is None:
            logger.warning(
                f"[SCHEMA_BUILDER] No column resolved for metric '{metric.raw_text}', skipping"
            )
            continue
        agg = SchemaAggregation(
            function=metric.aggregation_hint,
            column=col,
            alias=_agg_alias(metric.aggregation_hint, col),
        )
        aggregations.append(agg)

    # ------------------------------------------------------------------
    # 2. Entities → filters or group_by
    # ------------------------------------------------------------------
    # Group comparison_value entities by their resolved column so we can
    # emit a single IN filter instead of multiple AND= filters.
    comparison_groups: Dict[str, List[str]] = defaultdict(list)

    for entity in intent.entities:
        tm = term_resolution.get(entity.raw_text)
        col = (tm.column_name if tm else None) or entity.column_hint
        if col is None:
            logger.warning(
                f"[SCHEMA_BUILDER] No column resolved for '{entity.raw_text}' "
                f"(entity_type={entity.entity_type}), skipping"
            )
            continue

        if entity.entity_type == "dimension":
            # Dimension → GROUP BY
            if col not in group_by:
                group_by.append(col)

        elif entity.entity_type == "comparison_value":
            # Accumulate for single IN filter per column
            comparison_groups[col].append(entity.raw_text)

        elif entity.entity_type == "filter_value":
            # Regular filter — may be pre-built (filter_structured) or simple equality
            sf = _build_filter_from_entity(entity.raw_text, col, tm)
            filters.append(sf)

    # Emit IN filters for comparison groups
    for col, values in comparison_groups.items():
        if len(values) == 1:
            # Single comparison value — simple equality
            filters.append(
                SchemaFilter(
                    column=col,
                    operator="=",
                    value=values[0],
                    value_hint=values[0],
                )
            )
        else:
            filters.append(
                SchemaFilter(
                    column=col,
                    operator="IN",
                    values=values,
                    value_hint=", ".join(values),
                )
            )

        # For COMPARISON / TIME_SERIES_COMPARISON set comparison_dimension
        if query_type in ("COMPARISON", "TIME_SERIES_COMPARISON"):
            if comparison_dimension is None:
                comparison_dimension = col
            if col not in group_by:
                group_by.append(col)

    # ------------------------------------------------------------------
    # 3. Time → date filter + (optional) granularity
    # ------------------------------------------------------------------
    if intent.time is not None:
        # When time_breakdown flag is forced True, temporarily patch breakdown
        effective_st = intent.time
        if time_breakdown and not intent.time.breakdown:
            from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
            effective_st = SemanticTime(
                raw_text=intent.time.raw_text,
                breakdown=True,
            )

        try:
            date_descriptor, gran = parse_semantic_time(effective_st, today)
        except SemanticExtractionError as exc:
            raise SchemaBuilderError(
                f"Tarih ifadesi çözümlenemedi: {intent.time.raw_text!r}",
                error_code="DATE_PARSE_ERROR",
                context={"raw_text": intent.time.raw_text, "cause": str(exc)},
            ) from exc

        if date_descriptor is not None:
            filters.append(
                SchemaFilter(
                    column="DocumentDate",
                    operator=">=",
                    date_descriptor=date_descriptor,
                    value_hint=intent.time.raw_text,
                )
            )

        if gran is not None:
            time_granularity = gran

    # ------------------------------------------------------------------
    # 4. Build description
    # ------------------------------------------------------------------
    description = (
        f"{query_type} query: {intent.raw_query or 'n/a'}"
    )

    # ------------------------------------------------------------------
    # 5. select_columns — empty when aggregations are present
    # ------------------------------------------------------------------
    select_columns: List[str] = []

    # ------------------------------------------------------------------
    # 6. order_by / limit from intent
    # ------------------------------------------------------------------
    order_by_column: Optional[str] = None
    order_by_direction = intent.order_direction or "DESC"
    limit = intent.limit

    # For aggregation queries set order_by to the first aggregation alias
    if aggregations and query_type in ("RANKING",):
        order_by_column = aggregations[0].alias

    return QuerySchema(
        description=description,
        select_columns=select_columns,
        filters=filters,
        aggregations=aggregations,
        group_by=group_by,
        time_granularity=time_granularity,
        comparison_dimension=comparison_dimension,
        order_by_column=order_by_column,
        order_by_direction=order_by_direction,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_filter_from_entity(
    raw_text: str,
    col: str,
    tm: Optional[TermMatch],
) -> SchemaFilter:
    """Build a SchemaFilter for a filter_value entity.

    When the TermMatch has a pre-built filter_structured dict, use its column/
    operator/value directly. value_hint is always set to the original raw_text.
    """
    if tm is not None and tm.filter_structured is not None:
        fs = tm.filter_structured
        # Resolve column from filter_structured if present, otherwise use tm.column_name
        column = fs.get("column", col)
        operator = fs.get("operator", "=")
        value = fs.get("value")
        values_list = fs.get("values")
        return SchemaFilter(
            column=column,
            operator=operator,
            value=str(value) if value is not None else None,
            values=values_list,
            value_hint=raw_text,
        )

    # Default: simple equality filter using raw_text as value hint
    return SchemaFilter(
        column=col,
        operator="=",
        value_hint=raw_text,
        # value intentionally None — value_resolver will fill resolved_value later
    )
