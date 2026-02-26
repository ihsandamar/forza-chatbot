"""
AnalysisAgent — Report V2

LangGraph native parallel fan-out after check_results:
  check_results
       ├─→ extract_insights   (writes ONLY _business_insights)
       └─→ decide_viz         (writes ONLY _viz_decision, _should_visualize, _viz_reasoning)
            ↓
       build_analysis_result  (fan-in — assembles AnalysisResult)
            ↓
           END

Early exit path (when no_records_message or error):
  check_results → build_analysis_result  (skips parallel branch)
"""

import logging
from typing import Dict, Any, Optional, List

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from src.graphs.report.state import ActiveQueryContext, BusinessContext
from src.graphs.report_v2.state import AnalysisResult

logger = logging.getLogger(__name__)


# =============================================================================
# ANALYSIS STATE
# =============================================================================

class AnalysisState(TypedDict):
    # INPUT
    results: List[Dict[str, Any]]
    query_type: str
    user_query: str
    active_context: Optional[ActiveQueryContext]
    no_records_message: Optional[str]
    error: Optional[str]
    # Parallel node outputs (different keys — no conflict)
    _business_insights: Optional[BusinessContext]   # extract_insights_node writes this
    _viz_decision: Optional[Dict[str, Any]]         # decide_viz_node writes this
    _should_visualize: Optional[bool]               # decide_viz_node writes this
    _viz_reasoning: Optional[str]                   # decide_viz_node writes this
    # OUTPUT
    analysis_result: Optional[AnalysisResult]


# =============================================================================
# HELPER: create_analysis_input
# =============================================================================

def create_analysis_input(orch_state, classify_result, sql_result) -> AnalysisState:
    """
    Maps OrchestratorState + ClassifyResult + SQLResult → AnalysisState.

    Args:
        orch_state: OrchestratorState dict
        classify_result: ClassifyResult dict
        sql_result: SQLResult dict

    Returns:
        AnalysisState ready for graph invocation
    """
    return AnalysisState(
        results=sql_result.get("results", []),
        query_type=classify_result.get("query_type", "unknown"),
        user_query=classify_result.get("user_query", ""),
        active_context=orch_state.get("active_context"),
        no_records_message=sql_result.get("no_records_message"),
        error=sql_result.get("error"),
        _business_insights=None,
        _viz_decision=None,
        _should_visualize=None,
        _viz_reasoning=None,
        analysis_result=None,
    )


# =============================================================================
# NODE 1: check_results_node
# =============================================================================

async def check_results_node(state: AnalysisState) -> Dict[str, Any]:
    """
    Check if results are valid (not empty / not error).

    Migrated from check_results_node() in report/nodes.py.
    Simplified for the V2 architecture — no HITL, no resolution_metadata.

    Decision:
    - error present → propagate error, signal early exit
    - results empty → set no_records_message, signal early exit
    - results valid → no update needed; parallel branch proceeds
    """
    # Propagate upstream error
    error = state.get("error")
    if error:
        logger.warning(f"[ANALYSIS] Previous error detected: {error}")
        return {"error": error}

    results = state.get("results", [])
    logger.info(f"[ANALYSIS] Checking results: {len(results)} rows")

    if not results or len(results) == 0:
        logger.info("[ANALYSIS] Empty results, setting no_records_message")
        no_records_message = state.get("no_records_message") or "Sorguya uygun kayıt bulunamadı."
        return {"no_records_message": no_records_message}

    # Results are valid — nothing to update, fan-out will proceed
    logger.info(f"[ANALYSIS] Results OK ({len(results)} rows), proceeding to parallel branch")
    return {}


# =============================================================================
# NODE 2: extract_insights_node  (parallel — writes ONLY _business_insights)
# =============================================================================

def _make_extract_insights_node(business_tracker=None):
    """
    Factory for extract_insights_node.
    Returns an async node that writes ONLY to _business_insights.

    Migrated from create_business_insights_node() in report/nodes.py.

    Args:
        business_tracker: Optional BusinessContextTracker instance.
                          If None, returns a minimal business context.
    """

    async def extract_insights_node(state: AnalysisState) -> Dict[str, Any]:
        """
        Extract business insights from query results.
        Writes ONLY to _business_insights.

        Early-exit: if no_records_message or error is present, returns empty
        insights without calling LLM.
        """
        # Early exit — parallel path but results are invalid
        if state.get("no_records_message") or state.get("error"):
            logger.info("[ANALYSIS] [EXTRACT_INSIGHTS] Skipping — no valid results")
            return {"_business_insights": None}

        results = state.get("results", [])
        if not results:
            logger.info("[ANALYSIS] [EXTRACT_INSIGHTS] Empty results, skipping insights")
            return {"_business_insights": None}

        user_query = state.get("user_query", "")
        active_context = state.get("active_context")

        if business_tracker is None:
            logger.info("[ANALYSIS] [EXTRACT_INSIGHTS] No business_tracker provided, returning None")
            return {"_business_insights": None}

        logger.info(f"[ANALYSIS] [EXTRACT_INSIGHTS] Extracting insights from {len(results)} results...")

        try:
            business_context = await business_tracker.extract_insights(
                user_query=user_query,
                data_results=results,
                active_context=active_context,
                previous_business_context=None,
            )

            logger.info(
                f"[ANALYSIS] [EXTRACT_INSIGHTS] Extracted "
                f"{len(business_context.get('key_insights', []))} insights"
            )

            return {"_business_insights": business_context}

        except Exception as e:
            logger.error(f"[ANALYSIS] [EXTRACT_INSIGHTS] Error: {e}", exc_info=True)
            return {"_business_insights": None}

    return extract_insights_node


# =============================================================================
# NODE 3: decide_viz_node  (parallel — writes ONLY _viz_decision, _should_visualize, _viz_reasoning)
# =============================================================================

def _make_decide_viz_node(report_interpreter=None):
    """
    Factory for decide_viz_node.
    Returns an async node that writes ONLY to _viz_decision, _should_visualize, _viz_reasoning.

    Decision Priority:
    1. User explicit chart type request in query (keyword matching)
    2. query_type mapping (QUERY_TYPE_VIZ_MAPPING)
    3. Data shape analysis (fallback)
    4. LLM interpretation if report_interpreter is provided

    Migrated from decide_visualization_node() and create_llm_viz_decision_node()
    in report/nodes.py.

    Args:
        report_interpreter: Optional ReportInterpreter instance for LLM-assisted decisions.
    """

    async def decide_viz_node(state: AnalysisState) -> Dict[str, Any]:
        """
        Decide visualization type for query results.
        Writes ONLY to _viz_decision, _should_visualize, _viz_reasoning.

        Early-exit: if no_records_message or error is present, returns a
        no-graph decision without performing analysis.
        """
        from src.graphs.report.query_type_viz_mapping import (
            format_viz_decision,
            analyze_data_shape,
        )

        # Early exit — parallel path but results are invalid
        if state.get("no_records_message") or state.get("error"):
            logger.info("[ANALYSIS] [DECIDE_VIZ] Skipping — no valid results")
            no_graph_decision = {
                "needs_graph": False,
                "output_type": "table",
                "reasoning": "No valid results available",
            }
            return {
                "_viz_decision": no_graph_decision,
                "_should_visualize": False,
                "_viz_reasoning": "No valid results",
            }

        results = state.get("results", [])
        if not results:
            logger.info("[ANALYSIS] [DECIDE_VIZ] Empty results, no visualization")
            empty_decision = {
                "needs_graph": False,
                "output_type": "table",
                "reason": "Sonuç yok",
            }
            return {
                "_viz_decision": empty_decision,
                "_should_visualize": False,
                "_viz_reasoning": "Empty results",
            }

        query_type = state.get("query_type", "unknown")
        user_query = state.get("user_query", "")

        # Analyze data shape (used for fallback and single_value detection)
        data_shape = analyze_data_shape(results)

        # Quick decision: Single value
        if data_shape.get("is_single_value"):
            logger.info("[ANALYSIS] [DECIDE_VIZ] Single value detected, no graph needed")
            single_value_decision = {
                "needs_graph": False,
                "output_type": "single_value",
                "reason": "Tek değer sonucu",
                "data_shape": data_shape,
            }
            return {
                "_viz_decision": single_value_decision,
                "_should_visualize": False,
                "_viz_reasoning": "Quick rule: Single value",
            }

        # PRIORITY 1: Check user query for explicit chart type request
        user_query_lower = user_query.lower()

        chart_names = {
            "bar": ["çubuk", "막대", "bar"],
            "line": ["çizgi", "line"],
            "pie": ["pasta", "pie", "daire"],
            "scatter": ["scatter", "nokta", "saçılım"],
            "sunburst": ["sunburst", "hiyerarşik"],
            "treemap": ["treemap", "ağaç"],
        }
        chart_indicators = ["grafik", "chart", "olarak", "ver", "yap", "göster"]

        detected_chart_type = None
        for chart_type, names in chart_names.items():
            for name in names:
                if name in user_query_lower:
                    if any(indicator in user_query_lower for indicator in chart_indicators):
                        detected_chart_type = f"{chart_type}_chart"
                        logger.info(
                            f"[ANALYSIS] [DECIDE_VIZ] [PRIORITY 1] "
                            f"User explicitly requested: {detected_chart_type}"
                        )
                        break
            if detected_chart_type:
                break

        if detected_chart_type:
            if query_type and query_type != "unknown":
                viz_decision = format_viz_decision(
                    query_type=query_type,
                    override_chart_type=detected_chart_type,
                    data_shape=data_shape,
                )
                viz_decision["reasoning"] = (
                    f"Kullanıcı {detected_chart_type} istedi (query_type: {query_type})"
                )
            else:
                viz_decision = {
                    "needs_graph": True,
                    "output_type": detected_chart_type,
                    "chart_type": detected_chart_type,
                    "reasoning": f"Kullanıcı {detected_chart_type} istedi",
                    "query_type_driven": False,
                    "data_shape": data_shape,
                }
            return {
                "_viz_decision": viz_decision,
                "_should_visualize": viz_decision.get("needs_graph", True),
                "_viz_reasoning": viz_decision.get("reasoning", ""),
            }

        # PRIORITY 2: query_type mapping
        if query_type and query_type not in ("unknown", ""):
            logger.info(
                f"[ANALYSIS] [DECIDE_VIZ] [PRIORITY 2] "
                f"Using query_type={query_type} for viz decision"
            )
            viz_decision = format_viz_decision(query_type=query_type, data_shape=data_shape)
            logger.info(
                f"[ANALYSIS] [DECIDE_VIZ] Query type decision: {viz_decision['output_type']} "
                f"(needs_graph={viz_decision['needs_graph']})"
            )
            return {
                "_viz_decision": viz_decision,
                "_should_visualize": viz_decision.get("needs_graph", False),
                "_viz_reasoning": viz_decision.get("reasoning", ""),
            }

        # PRIORITY 3: LLM interpretation (if interpreter provided)
        if report_interpreter is not None:
            logger.info("[ANALYSIS] [DECIDE_VIZ] [PRIORITY 3] Using LLM interpretation")
            try:
                active_context = state.get("active_context")
                interpretation = await report_interpreter.interpret_results(
                    user_query=user_query,
                    data_results=results,
                    active_context=active_context,
                )
                viz_decision = interpretation.dict()
                logger.info(
                    f"[ANALYSIS] [DECIDE_VIZ] LLM decision: "
                    f"{interpretation.output_type} (needs_graph={interpretation.needs_graph})"
                )
                return {
                    "_viz_decision": viz_decision,
                    "_should_visualize": interpretation.needs_graph,
                    "_viz_reasoning": interpretation.reasoning,
                }
            except Exception as e:
                logger.error(f"[ANALYSIS] [DECIDE_VIZ] LLM interpretation error: {e}", exc_info=True)
                # Fall through to data shape fallback

        # PRIORITY 4: Data shape analysis fallback
        logger.info("[ANALYSIS] [DECIDE_VIZ] [PRIORITY 4] Using data shape analysis fallback")

        if data_shape.get("is_time_series") and data_shape.get("row_count", 0) > 2:
            viz_decision = {
                "needs_graph": True,
                "output_type": "line_chart",
                "chart_type": "line_chart",
                "reasoning": "Zaman serisi verisi tespit edildi",
                "query_type_driven": False,
                "data_shape": data_shape,
            }
        elif data_shape.get("row_count", 0) <= 10 and data_shape.get("column_count", 0) == 2:
            viz_decision = {
                "needs_graph": True,
                "output_type": "bar_chart",
                "chart_type": "bar_chart",
                "reasoning": "Küçük kategorik veri (bar chart uygun)",
                "query_type_driven": False,
                "data_shape": data_shape,
            }
        elif data_shape.get("row_count", 0) <= 20:
            viz_decision = {
                "needs_graph": False,
                "output_type": "simple_list",
                "reasoning": "Küçük sonuç seti (liste gösterimi)",
                "query_type_driven": False,
                "data_shape": data_shape,
            }
        else:
            viz_decision = {
                "needs_graph": False,
                "output_type": "table",
                "reasoning": "Büyük sonuç seti (tablo gösterimi)",
                "query_type_driven": False,
                "data_shape": data_shape,
            }

        logger.info(
            f"[ANALYSIS] [DECIDE_VIZ] Data shape fallback: {viz_decision['output_type']} "
            f"(needs_graph={viz_decision['needs_graph']})"
        )

        return {
            "_viz_decision": viz_decision,
            "_should_visualize": viz_decision.get("needs_graph", False),
            "_viz_reasoning": viz_decision.get("reasoning", ""),
        }

    return decide_viz_node


# =============================================================================
# NODE 4: build_analysis_result_node  (fan-in)
# =============================================================================

async def build_analysis_result_node(state: AnalysisState) -> Dict[str, Any]:
    """
    Fan-in node: reads _business_insights, _viz_decision, _should_visualize,
    _viz_reasoning and assembles AnalysisResult.

    Handles both the early-exit path (no_records_message / error) and
    the normal path (after parallel branch completes).
    """
    no_records_message = state.get("no_records_message")
    error = state.get("error")

    # Early exit path — no valid results
    if no_records_message or error:
        logger.info(
            f"[ANALYSIS] [BUILD_RESULT] Early exit — "
            f"no_records_message={no_records_message}, error={error}"
        )
        fallback_viz_decision: Dict[str, Any] = {
            "needs_graph": False,
            "output_type": "table",
            "reasoning": no_records_message or error or "No valid results",
        }
        result: AnalysisResult = {
            "should_visualize": False,
            "viz_decision": fallback_viz_decision,
            "business_insights": None,
            "viz_reasoning": no_records_message or error or "No valid results",
        }
        return {"analysis_result": result}

    # Normal path — read parallel branch outputs
    business_insights = state.get("_business_insights")
    viz_decision = state.get("_viz_decision") or {
        "needs_graph": False,
        "output_type": "table",
        "reasoning": "No visualization decision available",
    }
    should_visualize = state.get("_should_visualize")
    viz_reasoning = state.get("_viz_reasoning")

    # Derive should_visualize from viz_decision if not explicitly set
    if should_visualize is None:
        should_visualize = bool(viz_decision.get("needs_graph", False))

    result: AnalysisResult = {
        "should_visualize": should_visualize,
        "viz_decision": viz_decision,
        "business_insights": business_insights,
        "viz_reasoning": viz_reasoning,
    }

    logger.info(
        f"[ANALYSIS] [BUILD_RESULT] AnalysisResult assembled: "
        f"should_visualize={should_visualize}, "
        f"output_type={viz_decision.get('output_type', 'unknown')}, "
        f"has_insights={business_insights is not None}"
    )

    return {"analysis_result": result}


# =============================================================================
# ROUTING
# =============================================================================

def route_after_check(state: AnalysisState) -> str:
    """
    Route after check_results.

    - no_records_message or error → build_result (early exit, skip parallel branch)
    - otherwise → extract_insights (fan-out begins)

    NOTE: LangGraph also requires a direct edge from check_results → decide_viz
    to achieve true parallelism. That edge is added in build_analysis_agent().
    The conditional edge here handles both the early-exit route AND the fan-out
    start for extract_insights.
    """
    if state.get("no_records_message") or state.get("error"):
        logger.info("[ANALYSIS] [ROUTE] Early exit → build_analysis_result")
        return "build_result"

    logger.info("[ANALYSIS] [ROUTE] Normal path → extract_insights (fan-out)")
    return "extract_insights"


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_analysis_agent(business_tracker=None, report_interpreter=None):
    """
    Build and compile the analysis agent graph with LangGraph native parallelism.

    Architecture:
        START → check_results
                ├─(no results/error)→ build_analysis_result → END
                ├─(ok)─→ extract_insights ──┐
                └─(ok)─→ decide_viz ─────────┤
                                             ↓
                                    build_analysis_result → END

    Args:
        business_tracker: Optional BusinessContextTracker instance.
        report_interpreter: Optional ReportInterpreter instance.

    Returns:
        Compiled LangGraph StateGraph.
    """
    # Build node functions with captured dependencies
    extract_insights_node = _make_extract_insights_node(business_tracker)
    decide_viz_node = _make_decide_viz_node(report_interpreter)

    graph = StateGraph(AnalysisState)

    graph.add_node("check_results", check_results_node)
    graph.add_node("extract_insights", extract_insights_node)
    graph.add_node("decide_viz", decide_viz_node)
    graph.add_node("build_analysis_result", build_analysis_result_node)

    graph.add_edge(START, "check_results")

    # Conditional edge: early exit to build_analysis_result, or fan-out to extract_insights.
    graph.add_conditional_edges(
        "check_results",
        route_after_check,
        {
            "build_result": "build_analysis_result",   # early exit — skip parallel branch
            "extract_insights": "extract_insights",    # happy path — fan-out begins
        },
    )
    # decide_viz always fans out (its internal guard handles error/no_records case)
    graph.add_edge("check_results", "decide_viz")

    # Fan-in: build_analysis_result waits for BOTH parallel nodes
    graph.add_edge("extract_insights", "build_analysis_result")
    graph.add_edge("decide_viz", "build_analysis_result")

    graph.add_edge("build_analysis_result", END)

    return graph.compile()
