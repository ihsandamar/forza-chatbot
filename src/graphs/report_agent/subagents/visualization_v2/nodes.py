"""
Visualization V2 — Graph Nodes

5 node:
    data_analyzer      - Pure Python: results -> DataProfile
    viz_decider        - Rule-based fast path + LLM fallback -> ChartSpec
    spec_validator     - Pure Python: ChartSpec validation/fix (5 rules)
    template_renderer  - Pure Python: ChartSpec -> Plotly HTML (deterministic)
    response_builder   - Pure Python: pack outputs -> visualization_output

KARAR KATMANI: data_analyzer, viz_decider, spec_validator
CIZIM KATMANI: template_renderer, response_builder
"""
import datetime as _dt
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from langchain_core.runnables import RunnableConfig

from src.graphs.report_agent.subagents.visualization_v2.data_analyzer import DataAnalyzer
from src.graphs.report_agent.subagents.visualization_v2.models import ChartSpec
from src.graphs.report_agent.subagents.visualization_v2.prompts import VIZ_DECIDER_PROMPT
from src.graphs.report_agent.subagents.visualization_v2.validator import validate_spec
from src.graphs.report_agent.subagents.visualization_v2.chart_renderer import render_chart
from src.graphs.report_agent.subagents.text2sql.nodes import AGGREGATE_PERIOD_GRANULARITIES

logger = logging.getLogger(__name__)

NO_GRAPH_TYPES = {"single_value", "simple_list", "table"}


def _get_configurable(config: Optional[RunnableConfig], key: str, fallback):
    if not config:
        return fallback
    configurable = config.get("configurable", {})
    if hasattr(configurable, key):
        val = getattr(configurable, key)
    elif isinstance(configurable, dict):
        val = configurable.get(key)
    else:
        return fallback
    if val is None or val == "" or val == {}:
        return fallback
    return val


# =========================================================================
# HELPERS (date normalization — copied from v1)
# =========================================================================

def _infer_date_column_from_metadata(config: Optional[RunnableConfig]) -> Optional[str]:
    column_metadata = _get_configurable(config, "column_metadata", None)
    if not column_metadata or not isinstance(column_metadata, dict):
        return None
    _DATE_HINTS = {"date", "tarih", "datetime", "zaman"}
    date_cols = [
        col for col, desc in column_metadata.items()
        if any(h in col.lower() for h in _DATE_HINTS)
        or any(h in str(desc).lower() for h in _DATE_HINTS)
    ]
    return date_cols[0] if len(date_cols) == 1 else None


def _normalize_results(
    results: List[Dict[str, Any]],
    date_column_hint: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not results:
        return results

    column_renames: Dict[str, str] = {}
    if "" in results[0]:
        column_renames[""] = date_column_hint or "Date"

    normalized = []
    for row in results:
        new_row: Dict[str, Any] = {}
        for key, val in row.items():
            new_key = column_renames.get(key, key)
            if isinstance(val, _dt.datetime):
                val = val.date().isoformat()
            elif isinstance(val, _dt.date):
                val = val.isoformat()
            elif (
                isinstance(val, list)
                and len(val) == 3
                and all(isinstance(x, int) for x in val)
            ):
                try:
                    val = _dt.date(val[0], val[1], val[2]).isoformat()
                except (ValueError, TypeError):
                    pass
            new_row[new_key] = val
        normalized.append(new_row)
    return normalized


# =========================================================================
# NODE 1: DATA ANALYZER (Karar Katmani)
# =========================================================================

async def data_analyzer_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
    results = state.get("results") or []
    if not results:
        logger.info("[V2:DATA_ANALYZER] No results, skipping")
        return {"data_profile": None}

    date_hint = _infer_date_column_from_metadata(config)
    normalized = _normalize_results(results, date_column_hint=date_hint)

    analyzer = DataAnalyzer()
    profile_state = analyzer.analyze({"raw_data": normalized})
    profile = profile_state.get("data_profile")

    if profile:
        logger.info(
            f"[V2:DATA_ANALYZER] {profile['row_count']} rows, "
            f"dims={profile['dimension_columns']}, "
            f"metrics={profile['metric_columns']}, "
            f"time={profile.get('time_column')}"
        )
    return {"data_profile": profile, "results": normalized}


# =========================================================================
# NODE 2: VIZ DECIDER (Karar Katmani)
# =========================================================================

def _rule_based_decision(
    query_type: str,
    wants_viz: bool,
    profile: dict,
    time_granularity: Optional[str] = None,
    comparison_dimension: Optional[str] = None,
) -> Optional[dict]:
    """
    Deterministic chart type selection.
    Uses time_granularity + comparison_dimension for smarter multi-dim routing.
    Returns None -> LLM fallback.
    """
    if not wants_viz:
        return None

    metric_cols = profile.get("metric_columns", [])
    time_col = profile.get("time_column")
    dim_cols = profile.get("dimension_columns", [])
    row_count = profile.get("row_count", 0)

    if not metric_cols:
        return None

    if query_type == "LISTING":
        return {
            "needs_graph": False, "chart_type": "table",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "LISTING -> table",
        }

    if query_type == "SINGLE" and row_count == 1 and len(metric_cols) == 1:
        return {
            "needs_graph": False, "chart_type": "single_value",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Single value result",
        }

    # --- AGGREGATE PERIOD routing (hour_of_day, day_of_week, day_of_month) ---
    _AGG_X_FIELD_MAP = {"hour_of_day": "Saat", "day_of_week": "HaftaGunu", "day_of_month": "AyinGunu"}
    if time_granularity and time_granularity in AGGREGATE_PERIOD_GRANULARITIES:
        x_field = _AGG_X_FIELD_MAP.get(time_granularity)
        if comparison_dimension:
            # entity x period -> heatmap
            return {
                "needs_graph": True, "chart_type": "heatmap",
                "x_field": x_field, "y_field": None,
                "series_field": comparison_dimension,
                "reason": f"Aggregate period ({time_granularity}) + entity ({comparison_dimension}) -> heatmap",
            }
        else:
            # simple period distribution -> bar_chart
            return {
                "needs_graph": True, "chart_type": "bar_chart",
                "x_field": x_field, "y_field": None,
                "series_field": None,
                "reason": f"Aggregate period distribution ({time_granularity})",
            }

    # --- TIME_SERIES_COMPARISON routing ---
    if query_type == "TIME_SERIES_COMPARISON":
        if comparison_dimension:
            # entity + time trend -> multi-line (each entity = 1 line)
            return {
                "needs_graph": True, "chart_type": "line_chart",
                "x_field": None, "y_field": None,
                "series_field": comparison_dimension,
                "reason": f"Time series + entity ({comparison_dimension}) -> multi-line",
            }
        has_dims = len(dim_cols) >= 1
        if has_dims:
            # Dimension columns exist but comparison_dimension wasn't set by text2sql.
            # Fall back to LLM for correct field mapping.
            return None
        # simple time series (no entity)
        return {
            "needs_graph": True, "chart_type": "line_chart",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Simple time series -> line chart",
        }

    if query_type == "TIME_SERIES":
        return {
            "needs_graph": True, "chart_type": "line_chart",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Time series -> line chart",
        }

    # --- COMPARISON / RANKING with multiple dimensions -> sunburst ---
    if query_type in ("COMPARISON", "RANKING") and len(dim_cols) >= 2 and not time_col:
        return {
            "needs_graph": True, "chart_type": "sunburst",
            "x_field": None, "y_field": None, "series_field": None,
            "hierarchy_fields": dim_cols[:3],  # max 3 levels
            "reason": f"Multi-dimension hierarchy ({dim_cols[:3]}) -> sunburst",
        }

    if query_type == "RANKING":
        return {
            "needs_graph": True, "chart_type": "bar_chart",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Ranking -> bar chart",
        }

    if query_type == "COMPARISON":
        return {
            "needs_graph": True, "chart_type": "bar_chart",
            "x_field": None, "y_field": None, "series_field": None,
            "reason": "Comparison -> bar chart",
        }

    return None


def _build_conversation_context(state: dict, max_turns: int = 3) -> str:
    """Extract last N conversation turns as context for the LLM prompt."""
    messages = state.get("messages") or []
    if not messages:
        return "Onceki konusma yok."

    relevant = []
    for msg in messages[-(max_turns * 2):]:
        msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
        content = getattr(msg, "content", None) or (msg.get("content", "") if isinstance(msg, dict) else "")

        if not content:
            continue
        if len(str(content)) > 500:
            content = str(content)[:500] + "..."

        if msg_type == "human":
            relevant.append(f"Kullanici: {content}")
        elif msg_type == "ai":
            relevant.append(f"Sistem: {content}")

    return "\n".join(relevant) if relevant else "Onceki konusma yok."


def _build_column_info(profile: dict, column_metadata: dict) -> str:
    """Format column info for LLM prompt: name (role, type): description."""
    lines = []
    for col_info in profile.get("columns", []):
        name = col_info.get("name", "")
        role = col_info.get("role", "unknown")
        col_type = col_info.get("type", "unknown")
        desc = column_metadata.get(name, "")
        if isinstance(desc, dict):
            desc = desc.get("description", "")
        lines.append(f"- {name} ({role}, {col_type}): {desc}")
    return "\n".join(lines) or "Kolon bilgisi yok"


def create_viz_decider_node(llm) -> Callable:
    structured_llm = llm.with_structured_output(ChartSpec)

    async def viz_decider_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        results = state.get("results") or []
        data_profile = state.get("data_profile")

        # Fast exit: no data
        if not results:
            return {"viz_decision": ChartSpec(
                needs_graph=False, chart_type="table", reason="Veri yok"
            ).model_dump()}

        # Fast exit: no viz requested
        if not state.get("wants_visualization", False):
            return {"viz_decision": ChartSpec(
                needs_graph=False, chart_type="table", reason="Grafik talep edilmedi"
            ).model_dump()}

        # Fast exit: single value
        if len(results) == 1 and data_profile and data_profile.get("column_count", 0) == 1:
            return {"viz_decision": ChartSpec(
                needs_graph=False, chart_type="single_value", reason="Tek deger"
            ).model_dump()}

        _time_gran = state.get("time_granularity")
        _comp_dim = state.get("comparison_dimension")

        # Rule-based fast path (includes aggregate period routing)
        rule_decision = _rule_based_decision(
            query_type=state.get("query_type", ""),
            wants_viz=state.get("wants_visualization", False),
            profile=data_profile or {},
            time_granularity=_time_gran,
            comparison_dimension=_comp_dim,
        )
        if rule_decision is not None:
            logger.info(f"[V2:VIZ_DECIDER] Rule-based: {rule_decision['chart_type']}")
            return {"viz_decision": rule_decision}

        # LLM fallback
        wants_viz = state.get("wants_visualization", False)
        profile = data_profile or {}
        column_metadata = _get_configurable(config, "column_metadata", {})
        if isinstance(column_metadata, str):
            try:
                column_metadata = json.loads(column_metadata)
            except (json.JSONDecodeError, TypeError):
                column_metadata = {}

        effective_query = state.get("viz_request") or state.get("user_query", "")
        column_info = _build_column_info(profile, column_metadata)

        conversation_context = _build_conversation_context(state)

        prompt = VIZ_DECIDER_PROMPT.format(
            user_query=effective_query,
            query_type=state.get("query_type", "SINGLE"),
            wants_visualization=wants_viz,
            time_granularity=state.get("time_granularity") or "N/A",  # NEW
            column_info=column_info,
            sample_rows=json.dumps(results[:3], ensure_ascii=False, indent=2),
            conversation_context=conversation_context,
        )

        decision: ChartSpec = await structured_llm.ainvoke(prompt)

        # Guard: user wants viz but LLM says no
        if wants_viz and not decision.needs_graph:
            safe_chart = decision.chart_type
            if safe_chart in NO_GRAPH_TYPES:
                safe_chart = "bar_chart"
            decision = decision.model_copy(update={
                "needs_graph": True,
                "chart_type": safe_chart,
                "reason": decision.reason + " [override: user requested chart]",
            })

        logger.info(
            f"[V2:VIZ_DECIDER] LLM: {decision.chart_type}, "
            f"x={decision.x_field}, y={decision.y_field}"
        )
        return {"viz_decision": decision.model_dump()}

    return viz_decider_node


# =========================================================================
# NODE 3: SPEC VALIDATOR (Karar Katmani)
# =========================================================================

async def spec_validator_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
    viz_decision = state.get("viz_decision") or {}
    results = state.get("results") or []
    profile = state.get("data_profile") or {}

    if not results or not viz_decision.get("needs_graph", False):
        return {}  # No validation needed for non-graph outputs

    validated = validate_spec(viz_decision, results, profile)
    logger.info(
        f"[V2:VALIDATOR] {validated.get('chart_type')}, "
        f"x={validated.get('x_field')}, y={validated.get('y_field')}"
    )
    return {"viz_decision": validated}


# =========================================================================
# NODE 4: TEMPLATE RENDERER (Cizim Katmani)
# =========================================================================

async def template_renderer_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
    viz_decision = state.get("viz_decision") or {}
    results = state.get("results") or []

    if not viz_decision.get("needs_graph", False):
        return {}

    column_metadata = _get_configurable(config, "column_metadata", {})
    if isinstance(column_metadata, str):
        try:
            column_metadata = json.loads(column_metadata)
        except (json.JSONDecodeError, TypeError):
            column_metadata = {}

    html = render_chart(viz_decision, results, column_metadata)

    if html is None:
        logger.warning("[V2:RENDERER] Template failed, falling back to table")
        return {
            "plotly_html_snippet": None,
            "viz_decision": {**viz_decision, "needs_graph": False, "chart_type": "table"},
        }

    logger.info(f"[V2:RENDERER] HTML: {len(html)} chars")
    return {"plotly_html_snippet": html}


# =========================================================================
# NODE 5: RESPONSE BUILDER (Cizim Katmani)
# =========================================================================

async def response_builder_node(state: dict) -> dict:
    results = state.get("results") or []
    viz_decision = state.get("viz_decision") or {}
    data_profile = state.get("data_profile") or {}
    html_snippet = state.get("plotly_html_snippet")

    chart_type = viz_decision.get("chart_type", "table")
    needs_graph = viz_decision.get("needs_graph", False)

    summary = _build_summary(chart_type, results, html_snippet)

    visualization_output = {
        "needs_graph": needs_graph,
        "chart_type": chart_type,
        "plotly_html_snippet": html_snippet,
        "summary": summary,
        "x_field": viz_decision.get("x_field"),
        "y_field": viz_decision.get("y_field"),
        "title": viz_decision.get("title"),
    }

    logger.info(f"[V2:RESPONSE] chart_type={chart_type}, has_html={bool(html_snippet)}")
    return {"visualization_output": visualization_output}


def _build_summary(chart_type: str, data: list, html_snippet: Optional[str]) -> str:
    if not data:
        return "Sonuc bulunamadi."
    row_count = len(data)
    if chart_type == "single_value":
        return str(list(data[0].values())[0]) if data else ""
    if chart_type == "simple_list":
        return _format_as_markdown_list(data)
    if chart_type == "table":
        col_count = len(data[0]) if data else 0
        return f"{row_count} satir, {col_count} kolon"
    if html_snippet:
        return f"{row_count} veri noktasi gosteriliyor."
    return f"{row_count} kayit"


def _format_as_markdown_list(data: List[Dict[str, Any]]) -> str:
    if not data:
        return "Sonuc bulunamadi."
    columns = list(data[0].keys())
    MAX_ROWS = 20
    if len(columns) == 1:
        items = [str(list(row.values())[0]) for row in data[:MAX_ROWS]]
        result = "\n".join(f"- {item}" for item in items)
    elif len(columns) == 2:
        items = [
            f"- **{list(row.values())[0]}**: {list(row.values())[1]}"
            for row in data[:MAX_ROWS]
        ]
        result = "\n".join(items)
    else:
        return f"{len(data)} kayit listelendi."
    if len(data) > MAX_ROWS:
        result += f"\n\n*({len(data)} kayittan ilk {MAX_ROWS}'i gosteriliyor)*"
    return result
