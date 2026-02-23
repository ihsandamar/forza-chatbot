"""
Visualization Subagent Nodes

4 node:
    data_analyzer    - Pure Python: results → DataProfile
    viz_decider      - LLM (Pydantic): DataProfile + query → VizDecision
    chart_generator  - LLM: VizDecision + data → Plotly code → HTML snippet
    response_builder - Pure Python: tüm çıktıları visualization_output'a paketle
"""
import json
import logging
from typing import Any, Callable, Dict, List

from src.graphs.report_agent.subagents.visualization.data_analyzer import DataAnalyzer
from src.graphs.report_agent.subagents.visualization.prompts import (
    VizDecision,
    VIZ_DECIDER_PROMPT,
    CHART_GENERATOR_PROMPT,
)

logger = logging.getLogger(__name__)

NO_GRAPH_TYPES = {"single_value", "simple_list", "table"}


# =============================================================================
# NODE 1: DATA ANALYZER
# =============================================================================

async def data_analyzer_node(state: dict) -> dict:
    """
    Pure Python: results → DataProfile.
    DataAnalyzer class'ı doğrudan kullanır (Türkçe pattern'ler dahil).
    """
    results = state.get("results") or []

    if not results:
        logger.info("[DATA_ANALYZER] No results, skipping analysis")
        return {"data_profile": None}

    analyzer = DataAnalyzer()
    # DataAnalyzer "raw_data" key'ini okur — results'ı map ediyoruz
    profile_state = analyzer.analyze({"raw_data": results})
    profile = profile_state.get("data_profile")

    if profile:
        logger.info(
            f"[DATA_ANALYZER] Profile: {profile['row_count']} rows, "
            f"{profile['column_count']} cols, "
            f"dims={profile['dimension_columns']}, "
            f"metrics={profile['metric_columns']}"
        )
    return {"data_profile": profile}


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
        profile = data_profile or {}
        prompt = VIZ_DECIDER_PROMPT.format(
            user_query=state.get("user_query", ""),
            query_type=state.get("query_type", "SINGLE"),
            row_count=profile.get("row_count", len(results)),
            dimension_columns=", ".join(profile.get("dimension_columns", [])) or "Yok",
            metric_columns=", ".join(profile.get("metric_columns", [])) or "Yok",
            time_column=profile.get("time_column") or "Yok",
            has_multiple_dimensions=profile.get("has_multiple_dimensions", False),
            sample_rows=json.dumps(results[:3], ensure_ascii=False, indent=2),
        )

        decision: VizDecision = await structured_llm.ainvoke(prompt)
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

        prompt = CHART_GENERATOR_PROMPT.format(
            viz_decision=json.dumps(viz_decision, ensure_ascii=False, indent=2),
            data=json.dumps(results, ensure_ascii=False),
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
        "data": results,
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
