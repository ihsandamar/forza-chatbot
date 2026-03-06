"""
Visualization Subagent Nodes

4 node:
    data_analyzer    - Pure Python: results → DataProfile
    viz_decider      - LLM (Pydantic): DataProfile + query → VizDecision
    chart_generator  - LLM: VizDecision + data → Plotly code → HTML snippet
    response_builder - Pure Python: tüm çıktıları visualization_output'a paketle
"""
import datetime as _dt
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from langchain_core.runnables import RunnableConfig

from src.graphs.report_agent.subagents.visualization.data_analyzer import DataAnalyzer
from src.graphs.report_agent.subagents.visualization.prompts import (
    VizDecision,
    VIZ_DECIDER_PROMPT,
    CHART_GENERATOR_PROMPT,
)

logger = logging.getLogger(__name__)

NO_GRAPH_TYPES = {"single_value", "simple_list", "table"}
MAX_TRACES = 50


def _get_configurable(config: Optional[RunnableConfig], key: str, fallback):
    """RunnableConfig'ten değer oku; yoksa fallback döndür."""
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


def _infer_date_column_from_metadata(config: Optional[RunnableConfig]) -> Optional[str]:
    """
    Runtime config'teki column_metadata'dan tarih kolonunu tahmin eder.
    Tek bir tarih kolonu bulunursa onu döndürür; birden fazla veya yoksa None.
    """
    column_metadata = _get_configurable(config, "column_metadata", None)
    if not column_metadata or not isinstance(column_metadata, dict):
        return None

    _DATE_HINTS = {"date", "tarih", "datetime", "zaman"}
    date_cols = [
        col for col, desc in column_metadata.items()
        if any(h in col.lower() for h in _DATE_HINTS)
        or any(h in str(desc).lower() for h in _DATE_HINTS)
    ]
    if len(date_cols) == 1:
        return date_cols[0]
    if len(date_cols) > 1:
        logger.debug(f"[DATA_ANALYZER] Ambiguous date columns {date_cols}, no hint selected")
    return None


def _infer_date_column_from_values(rows: List[Dict[str, Any]], empty_key_target: str) -> str:
    """
    Boş-key kolonunun değerlerine bakarak tarih kolonu olup olmadığını doğrular.
    Tarihse empty_key_target'ı döndürür; değilse 'UnknownColumn' döndürür.

    [year, month, day] listesi kontrolü: yıl/ay/gün aralığı doğrulaması yaparak
    RGB, koordinat, versiyon tuple gibi false-positive'leri önler.
    """
    sample = rows[0].get("") if rows else None
    if sample is None:
        return empty_key_target

    is_date_value = (
        isinstance(sample, (_dt.date, _dt.datetime))
        or (
            isinstance(sample, list)
            and len(sample) == 3
            and all(isinstance(x, int) for x in sample)
            and 1900 <= sample[0] <= 2100  # yıl
            and 1 <= sample[1] <= 12        # ay
            and 1 <= sample[2] <= 31        # gün
        )
        or (
            isinstance(sample, str)
            and len(sample) >= 8
            and sample[:4].isdigit()
            and 1900 <= int(sample[:4]) <= 2100  # ISO tarih string'i için yıl aralığı
        )
    )
    return empty_key_target if is_date_value else "UnknownColumn"


def _normalize_results(
    results: List[Dict[str, Any]],
    date_column_hint: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Normalizes results list before visualization processing:
    - Converts datetime.date / datetime.datetime values to ISO strings (JSON serializable)
    - Renames empty-string column names using date_column_hint (from runtime config)
      or value-based detection; never hardcodes 'DocumentDate'
    - Handles [year, month, day] lists for ANY column (LangGraph checkpoint deserialization)
    """
    if not results:
        return results

    # Boş key varsa → rename hedefini dinamik belirle
    column_renames: Dict[str, str] = {}
    if "" in results[0]:
        candidate = date_column_hint or "Date"
        column_renames[""] = _infer_date_column_from_values(results, candidate)

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
                # LangGraph serializes datetime.date as [year, month, day] — herhangi bir kolona uygula
                try:
                    val = _dt.date(val[0], val[1], val[2]).isoformat()
                except (ValueError, TypeError):
                    pass
            new_row[new_key] = val
        normalized.append(new_row)
    return normalized


# =============================================================================
# NODE 1: DATA ANALYZER
# =============================================================================

async def data_analyzer_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
    """
    Pure Python: results → DataProfile.
    DataAnalyzer class'ı doğrudan kullanır (Türkçe pattern'ler dahil).
    """
    results = state.get("results") or []

    if not results:
        logger.info("[DATA_ANALYZER] No results, skipping analysis")
        return {"data_profile": None}

    # Boş-key kolon için runtime config'ten tarih kolonu adını al
    date_hint = _infer_date_column_from_metadata(config)
    if date_hint:
        logger.debug(f"[DATA_ANALYZER] Date column hint from config: '{date_hint}'")

    # Normalize: datetime.date → ISO string, boş kolon adı → dinamik rename
    normalized = _normalize_results(results, date_column_hint=date_hint)
    if normalized != results:
        logger.info("[DATA_ANALYZER] Results normalized (dates → ISO strings, empty columns renamed)")

    analyzer = DataAnalyzer()
    # DataAnalyzer "raw_data" key'ini okur — results'ı map ediyoruz
    profile_state = analyzer.analyze({"raw_data": normalized})
    profile = profile_state.get("data_profile")

    if profile:
        logger.info(
            f"[DATA_ANALYZER] Profile: {profile['row_count']} rows, "
            f"{profile['column_count']} cols, "
            f"dims={profile['dimension_columns']}, "
            f"metrics={profile['metric_columns']}, "
            f"time={profile.get('time_column')}"
        )
    # Propagate normalized results so downstream nodes (viz_decider, chart_generator) use clean data
    return {"data_profile": profile, "results": normalized}


# =============================================================================
# NODE 2: VIZ DECIDER
# =============================================================================

def create_viz_decider_node(llm) -> Callable:
    """
    LLM (Pydantic structured output): DataProfile + user_query → VizDecision.
    Boş veri ve tek değer için LLM'e gitmeden hızlı karar verir.
    """
    structured_llm = llm.with_structured_output(VizDecision)

    async def viz_decider_node(state: dict) -> dict:
        results = state.get("results") or []
        data_profile = state.get("data_profile")

        # --- Hızlı kararlar (LLM yok) ---
        if not results:
            logger.info("[VIZ_DECIDER] No data → table (no graph)")
            return {"viz_decision": VizDecision(
                needs_graph=False, chart_type="table", reason="Veri yok"
            ).model_dump()}

        # Kullanıcı grafik istemedi → direkt tablo, LLM çağrısı yok
        if not state.get("wants_visualization", False):
            logger.info("[VIZ_DECIDER] wants_visualization=False → table (no graph)")
            return {"viz_decision": VizDecision(
                needs_graph=False, chart_type="table", reason="Kullanıcı grafik talep etmedi"
            ).model_dump()}

        if len(results) == 1 and data_profile and data_profile.get("column_count", 0) == 1:
            logger.info("[VIZ_DECIDER] Single value → no graph")
            return {"viz_decision": VizDecision(
                needs_graph=False, chart_type="single_value", reason="Tek değer sonucu"
            ).model_dump()}

        # --- LLM kararı ---
        wants_viz = state.get("wants_visualization", False)
        profile = data_profile or {}
        # viz_request varsa ("pasta grafik" gibi) onu kullan;
        # yoksa user_query'yi kullan (NEW_QUERY + wants_viz=True senaryosu).
        effective_query = state.get("viz_request") or state.get("user_query", "")
        prompt = VIZ_DECIDER_PROMPT.format(
            user_query=effective_query,
            query_type=state.get("query_type", "SINGLE"),
            wants_visualization=wants_viz,
            row_count=profile.get("row_count", len(results)),
            dimension_columns=", ".join(profile.get("dimension_columns", [])) or "Yok",
            metric_columns=", ".join(profile.get("metric_columns", [])) or "Yok",
            time_column=profile.get("time_column") or "Yok",
            has_multiple_dimensions=profile.get("has_multiple_dimensions", False),
            sample_rows=json.dumps(results[:3], ensure_ascii=False, indent=2),
        )

        decision: VizDecision = await structured_llm.ainvoke(prompt)

        # Savunmacı guard: kullanıcı grafik istedi ama LLM needs_graph=False döndürdüyse zorla
        if wants_viz and not decision.needs_graph:
            logger.warning(
                "[VIZ_DECIDER] wants_visualization=True but LLM returned needs_graph=False — overriding"
            )
            safe_chart = decision.chart_type
            if safe_chart in ("table", "single_value", "simple_list"):
                safe_chart = "bar_chart"  # fallback chart türü
            decision = VizDecision(
                needs_graph=True,
                chart_type=safe_chart,
                x_field=decision.x_field,
                y_field=decision.y_field,
                series_field=decision.series_field,
                title=decision.title,
                reason=decision.reason + " [needs_graph=True: user explicitly requested chart]",
            )

        logger.info(
            f"[VIZ_DECIDER] → {decision.chart_type}, "
            f"needs_graph={decision.needs_graph}, "
            f"x={decision.x_field}, y={decision.y_field}"
        )
        return {"viz_decision": decision.model_dump()}

    return viz_decider_node


# =============================================================================
# NODE 3: CHART GENERATOR
# =============================================================================

def _clean_plotly_code(code: str) -> str:
    """Markdown code block'larını temizle."""
    code = code.strip()
    if code.startswith("```"):
        lines = code.split("\n")
        lines = lines[1:]  # İlk satırı (```python) kaldır
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        code = "\n".join(lines)
    return code.strip()


def _execute_plotly_code(code: str, data: List[Dict[str, Any]]) -> str:
    """
    Plotly kodunu çalıştır ve HTML snippet döndür.
    go, px, pd ve data önceden inject edilmiş ortamda çalışır.
    """
    import plotly.graph_objects as go
    import plotly.express as px
    import pandas as pd

    exec_globals = {
        "__builtins__": __builtins__,
        "data": data,
        "go": go,
        "px": px,
        "pd": pd,
    }
    exec_locals: dict = {}

    exec(code, exec_globals, exec_locals)  # noqa: S102

    fig = exec_locals.get("fig") or exec_globals.get("fig")
    if fig is None:
        raise ValueError("Plotly kodu 'fig' değişkeni oluşturmadı")

    # Guard: cap trace count to prevent HTML bloat from bad LLM code
    if hasattr(fig, "data") and len(fig.data) > MAX_TRACES:
        logger.warning(
            f"[CHART_GENERATOR] Trace count {len(fig.data)} exceeds {MAX_TRACES}, capping"
        )
        fig.data = fig.data[:MAX_TRACES]

    return fig.to_html(include_plotlyjs="cdn", full_html=False)


def create_chart_generator_node(llm) -> Callable:
    """
    LLM: VizDecision + data → Plotly Python kodu → execute → HTML snippet.
    needs_graph=False ise conditional edge tarafından atlanır.
    """

    async def chart_generator_node(state: dict) -> dict:
        viz_decision = state.get("viz_decision") or {}
        results = state.get("results") or []

        if not viz_decision.get("needs_graph", False):
            logger.info("[CHART_GENERATOR] No graph needed, skipping")
            return {}

        sample_data = results[:5]
        prompt = CHART_GENERATOR_PROMPT.format(
            viz_decision=json.dumps(viz_decision, ensure_ascii=False, indent=2),
            sample_data=json.dumps(sample_data, ensure_ascii=False, indent=2),
            total_rows=len(results),
        )

        # LLM → Plotly Python kodu (serbest metin, structured output değil)
        response = await llm.ainvoke(prompt)
        raw_code = response.content if hasattr(response, "content") else str(response)
        code = _clean_plotly_code(raw_code)

        logger.info(f"[CHART_GENERATOR] Code generated ({len(code)} chars)")

        try:
            html_snippet = _execute_plotly_code(code, results)
            logger.info(f"[CHART_GENERATOR] HTML snippet: {len(html_snippet)} chars")
            return {"plotly_html_snippet": html_snippet}
        except Exception as e:
            logger.error(f"[CHART_GENERATOR] Execution error: {e}")
            return {"plotly_html_snippet": None, "error": f"Grafik oluşturulamadı: {e}"}

    return chart_generator_node


# =============================================================================
# NODE 4: RESPONSE BUILDER
# =============================================================================

async def response_builder_node(state: dict) -> dict:
    """
    Pure Python: tüm çıktıları visualization_output dict'e paketle.
    ResponseBuilder mantığını korur — LLM yok.
    """
    results = state.get("results") or []
    viz_decision = state.get("viz_decision") or {}
    data_profile = state.get("data_profile") or {}
    html_snippet = state.get("plotly_html_snippet")

    chart_type = viz_decision.get("chart_type", "table")
    needs_graph = viz_decision.get("needs_graph", False)

    summary = _build_summary(chart_type, results, data_profile, html_snippet)

    visualization_output = {
        "needs_graph": needs_graph,
        "chart_type": chart_type,
        "plotly_html_snippet": html_snippet,
        "summary": summary,
        "x_field": viz_decision.get("x_field"),
        "y_field": viz_decision.get("y_field"),
        "title": viz_decision.get("title"),
    }

    logger.info(f"[RESPONSE_BUILDER] Output: chart_type={chart_type}, has_html={bool(html_snippet)}")
    return {"visualization_output": visualization_output}


def _build_summary(
    chart_type: str,
    data: List[Dict[str, Any]],
    profile: Dict[str, Any],
    html_snippet: str | None,
) -> str:
    """Veri tipine göre özet metni oluştur."""
    if not data:
        return "Sonuç bulunamadı."

    row_count = len(data)

    if chart_type == "single_value":
        value = list(data[0].values())[0] if data else ""
        return str(value)

    if chart_type == "simple_list":
        return _format_as_markdown_list(data)

    if chart_type == "table":
        col_count = len(data[0]) if data else 0
        return f"{row_count} satır, {col_count} kolon"

    if html_snippet:
        return f"{row_count} veri noktası gösteriliyor."

    return f"{row_count} kayıt"


def _format_as_markdown_list(data: List[Dict[str, Any]]) -> str:
    """1-2 kolonlu veriyi markdown liste olarak formatla."""
    if not data:
        return "Sonuç bulunamadı."

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
        return f"{len(data)} kayıt listelendi."

    if len(data) > MAX_ROWS:
        result += f"\n\n*({len(data)} kayıttan ilk {MAX_ROWS}'i gösteriliyor)*"
    return result
