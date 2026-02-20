"""
ResponseAgent — Report V2

Simple single-node agent that consumes all other agent outputs
to produce the final response.

Graph structure:
    START → build_response → END

Two modes:
    response_generator=None  → template-based response
    response_generator=inst  → LLM-powered natural response
"""

import base64
import logging
from typing import Dict, Any, Optional, List

from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from src.graphs.report_v2.state import ClassifyResult, SQLResult, AnalysisResult

logger = logging.getLogger(__name__)


# =============================================================================
# RESPONSE STATE
# =============================================================================

class ResponseState(TypedDict):
    # INPUT
    classify_result: ClassifyResult
    sql_result: SQLResult
    analysis_result: AnalysisResult
    viz_artifact: Optional[Dict[str, Any]]
    messages: List[BaseMessage]
    # OUTPUT
    final_response: str


# =============================================================================
# HELPER: create_response_input
# =============================================================================

def create_response_input(
    orch_state: Dict[str, Any],
    classify_result: ClassifyResult,
    sql_result: SQLResult,
    analysis_result: AnalysisResult,
) -> ResponseState:
    """
    Maps OrchestratorState + agent results → ResponseState.

    Args:
        orch_state: OrchestratorState dict (or any compatible mapping)
        classify_result: Output from ClassifyAgent
        sql_result: Output from SQLAgent
        analysis_result: Output from AnalysisAgent

    Returns:
        ResponseState ready for the response agent graph.
    """
    return ResponseState(
        classify_result=classify_result,
        sql_result=sql_result,
        analysis_result=analysis_result,
        viz_artifact=orch_state.get("viz_artifact"),
        messages=orch_state.get("messages", []),
        final_response="",
    )


# =============================================================================
# NODE FACTORY: _make_build_response_node
# =============================================================================

def _make_build_response_node(response_generator=None):
    """
    Factory that returns the build_response node.

    Args:
        response_generator: ResponseGenerator instance (LLM path) or None
                            (template path).

    Returns:
        Async node function.
    """

    async def build_response_node(state: ResponseState) -> Dict[str, Any]:
        """
        Build the final response from all agent outputs.

        Migrated from build_response_node() and create_natural_response_node()
        in src/graphs/report/nodes.py.

        Template path (response_generator=None):
            - Formats SQL results as a numbered list.
            - Handles error / no-records / empty cases with simple messages.
            - Embeds Plotly HTML from viz_artifact in an <iframe> when present.

        LLM path (response_generator provided):
            - Delegates to ResponseGenerator.generate_response().
            - Falls back to template path on exception.
            - Appends Plotly <iframe> when viz_artifact and needs_graph are set.
        """
        classify_result: ClassifyResult = state.get("classify_result") or {}
        sql_result: SQLResult = state.get("sql_result") or {}
        analysis_result: AnalysisResult = state.get("analysis_result") or {}
        viz_artifact: Optional[Dict[str, Any]] = state.get("viz_artifact")

        # ------------------------------------------------------------------ #
        # Extract key fields
        # ------------------------------------------------------------------ #
        error: Optional[str] = sql_result.get("error")
        no_records: Optional[str] = sql_result.get("no_records_message")
        results: List[Dict[str, Any]] = sql_result.get("results") or []
        user_query: str = classify_result.get("user_query") or ""

        business_insights = analysis_result.get("business_insights")
        viz_decision: Optional[Dict[str, Any]] = analysis_result.get("viz_decision")

        # ------------------------------------------------------------------ #
        # LLM path
        # ------------------------------------------------------------------ #
        if response_generator is not None:
            logger.info("[RESPONSE_AGENT] [LLM] Generating natural language response...")
            try:
                response_text = await response_generator.generate_response(
                    user_query=user_query,
                    data_results=results if results else None,
                    business_context=business_insights,
                    visualization_info=viz_decision,
                    error=error,
                    no_records_message=no_records,
                )
                logger.info(
                    f"[RESPONSE_AGENT] [LLM] Generated response: {len(response_text)} chars"
                )

                # Append Plotly iframe when viz artifact is ready
                plotly_html = viz_artifact.get("plotly_html_snippet") if viz_artifact else None
                needs_graph = viz_decision.get("needs_graph", False) if viz_decision else False
                if plotly_html and needs_graph:
                    html_full = (
                        "<!DOCTYPE html>\n"
                        "<html><head><meta charset=\"UTF-8\"></head>\n"
                        f"<body style=\"margin:0\">{plotly_html}</body></html>"
                    )
                    html_b64 = base64.b64encode(
                        html_full.encode("utf-8")
                    ).decode("ascii")
                    iframe = (
                        f'<iframe src="data:text/html;charset=utf-8;base64,{html_b64}" '
                        'width="100%" height="500" frameborder="0"></iframe>'
                    )
                    response_text = f"{response_text}\n\n**Grafik:**\n{iframe}"

                return {"final_response": response_text}

            except Exception as exc:
                logger.error(
                    f"[RESPONSE_AGENT] [LLM] Response generation failed: {exc}. "
                    "Falling back to template path."
                )
                # Fall through to template path below

        # ------------------------------------------------------------------ #
        # Template path (also serves as fallback for LLM errors)
        # ------------------------------------------------------------------ #

        # Error case
        if error:
            response_text = f"Hata: {error}\n\nLutfen sorgunuzu yeniden ifade edin."
            logger.info("[RESPONSE_AGENT] [TEMPLATE] Error response")
            return {"final_response": response_text}

        # No-records case
        if no_records:
            response_text = (
                f"Sonuc Bulunamadi\n\n{no_records}\n\n"
                "Oneriler:\n"
                "- Filtre kriterlerini genisletin\n"
                "- Farkli bir zaman araligi deneyin\n"
                "- Sorgunuzu yeniden ifade edin"
            )
            logger.info("[RESPONSE_AGENT] [TEMPLATE] No-records response")
            return {"final_response": response_text}

        # Viz artifact with HTML — embed as iframe
        plotly_html = viz_artifact.get("plotly_html_snippet") if viz_artifact else None
        if plotly_html:
            html_full = (
                "<!DOCTYPE html>\n"
                "<html><head><meta charset=\"UTF-8\"></head>\n"
                f"<body style=\"margin:0\">{plotly_html}</body></html>"
            )
            html_b64 = base64.b64encode(
                html_full.encode("utf-8")
            ).decode("ascii")
            iframe = (
                f'<iframe src="data:text/html;charset=utf-8;base64,{html_b64}" '
                'width="100%" height="500" frameborder="0"></iframe>'
            )
            logger.info("[RESPONSE_AGENT] [TEMPLATE] Visualization response (iframe)")
            return {"final_response": f"Grafik:\n{iframe}"}

        # Data results
        if results:
            parts = [f"**Sonuclar** ({len(results)} kayit):\n"]
            for i, row in enumerate(results[:50], 1):
                row_str = " | ".join(
                    f"**{k}:** {v}" for k, v in row.items()
                )
                parts.append(f"{i}. {row_str}")

            if len(results) > 50:
                parts.append(f"\n... ve {len(results) - 50} kayit daha")

            # Append business insights if available
            if business_insights:
                insights = business_insights.get("key_insights", [])
                if insights:
                    parts.append("\n**Onemli Bulgular:**")
                    for insight in insights[:3]:
                        parts.append(f"- {insight}")

                follow_ups = business_insights.get("suggested_follow_ups", [])
                if follow_ups:
                    parts.append("\n**Ilgili Sorular:**")
                    for follow_up in follow_ups[:2]:
                        parts.append(f"- {follow_up}")

            logger.info(f"[RESPONSE_AGENT] [TEMPLATE] Data response ({len(results)} rows)")
            return {"final_response": "\n".join(parts)}

        # Empty / nothing to show
        logger.warning("[RESPONSE_AGENT] [TEMPLATE] No content found, returning fallback")
        return {"final_response": "Sonuc bulunamadi."}

    return build_response_node


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_response_agent(response_generator=None):
    """
    Build and compile the response agent graph.

    Args:
        response_generator: ResponseGenerator instance for LLM-powered natural
                            responses, or None for template-based responses.

    Returns:
        Compiled LangGraph StateGraph (single node: build_response → END).
    """
    build_response_node = _make_build_response_node(response_generator)

    graph = StateGraph(ResponseState)
    graph.add_node("build_response", build_response_node)
    graph.add_edge(START, "build_response")
    graph.add_edge("build_response", END)

    return graph.compile()
