"""
Report Graph - Stateful Report Agent

HITL destekli, context-aware rapor üretim sistemi.

Architecture:
    START
      ↓
    immediate_ack (instant feedback)
      ↓
    classify_intent (intent + confidence)
      ↓ (conditional)
    ├── [ask_user] ← interrupt_before (HITL)
    │      ↓
    │   process_clarification
    │      ↓
    ├── [rollback] → build_response
    │
    └── process_query
          ↓
        text2sql
          ↓
        check_results
          ↓ (conditional)
        ├── [ask_user] ← empty result recovery
        └── visualization
              ↓
            build_response
              ↓
            END

LangGraph Features Used:
- StateGraph with TypedDict
- Conditional edges (route_after_intent, route_after_results)
- interrupt_before for HITL
- Reducer functions for query_history
- Checkpointer for state persistence
"""

import logging
from typing import Optional

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.models.llm import LLM

from .state import ReportState
from .nodes import (
    immediate_acknowledgment_node,
    create_intent_classifier_node,
    process_user_clarification_node,
    extract_query_node,
    check_results_node,
    create_text2sql_node,
    create_visualization_node,
    rollback_node,
    build_response_node,
    route_after_intent,
    create_route_after_intent,
    route_after_results
)
from .tools import should_interrupt, format_interrupt_message

logger = logging.getLogger(__name__)


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_report_graph(
    text2sql_graph,
    visualization_graph,
    llm: Optional[LLM] = None,
    enable_hitl: bool = True,
    checkpointer=None,
    config_schema=None
) -> StateGraph:
    """
    Build the stateful report generation graph.

    Args:
        text2sql_graph: Compiled text2sql graph
        visualization_graph: Compiled visualization graph
        llm: Language model for intent classification (optional)
        enable_hitl: Enable HITL features (interrupt_before)
        checkpointer: State checkpointer (default: MemorySaver)
        config_schema: Configuration schema for runtime config (optional)
                      If not provided, uses GenericSQLAssistantConfiguration

    Returns:
        Compiled StateGraph
    """
    logger.info("[REPORT] Building stateful report graph...")

    # Import config schema if not provided
    if config_schema is None:
        from src.graphs.generic_text2sql.assistant_configuration import GenericSQLAssistantConfiguration
        config_schema = GenericSQLAssistantConfiguration

    # Create graph with enhanced state and config schema
    graph = StateGraph(ReportState, config_schema=config_schema)

    # Create node factories
    text2sql_node = create_text2sql_node(text2sql_graph)
    visualization_node = create_visualization_node(visualization_graph)

    # Intent classifier (LLM gerektirir)
    if llm:
        llm_chat = llm.get_chat()
        intent_classifier_node = create_intent_classifier_node(llm_chat)
        # LLM tabanlı akıllı router
        smart_router = create_route_after_intent(llm_chat)
        logger.info("[REPORT] Using LLM-based smart router")
    else:
        # Fallback: basit classifier (LLM olmadan)
        async def simple_intent_node(state: ReportState):
            return {"_intent_type": "new_query", "_confidence": 0.8}
        intent_classifier_node = simple_intent_node
        # Fallback: basit router
        smart_router = route_after_intent
        logger.info("[REPORT] Using simple rule-based router (no LLM)")

    # -------------------------------------------------------------------------
    # ADD NODES
    # -------------------------------------------------------------------------
    logger.info("[REPORT] Adding nodes...")

    # Immediate acknowledgment (instant feedback)
    graph.add_node("immediate_ack", immediate_acknowledgment_node)

    # Intent classification
    graph.add_node("classify_intent", intent_classifier_node)

    # HITL nodes
    if enable_hitl:
        graph.add_node("ask_user", _ask_user_node)
        graph.add_node("process_clarification", process_user_clarification_node)

    # Query processing
    graph.add_node("extract_query", extract_query_node)
    graph.add_node("text2sql", text2sql_node)
    graph.add_node("check_results", check_results_node)

    # Rollback
    graph.add_node("rollback", rollback_node)

    # Visualization and response
    graph.add_node("visualization", visualization_node)
    graph.add_node("build_response", build_response_node)

    # -------------------------------------------------------------------------
    # ADD EDGES
    # -------------------------------------------------------------------------
    logger.info("[REPORT] Adding edges...")

    # START → immediate_ack → classify_intent
    graph.add_edge(START, "immediate_ack")
    graph.add_edge("immediate_ack", "classify_intent")

    # classify_intent → conditional routing (LLM-based smart router)
    if enable_hitl:
        graph.add_conditional_edges(
            "classify_intent",
            smart_router,
            {
                "ask_user": "ask_user",
                "rollback": "rollback",
                "process_query": "extract_query"
            }
        )

        # HITL flow
        graph.add_edge("ask_user", "process_clarification")
        graph.add_edge("process_clarification", "extract_query")
    else:
        # HITL disabled: use smart router but skip ask_user
        # smart_router hala akıllı karar verir ama ask_user yerine process_query'ye yönlendirir
        async def hitl_disabled_router(state: ReportState) -> str:
            """HITL disabled router - ask_user yerine process_query'ye yönlendirir."""
            if llm:
                route = await smart_router(state)
                # ask_user devre dışı, process_query'ye yönlendir
                if route == "ask_user":
                    return "extract_query"
                return "rollback" if route == "rollback" else "extract_query"
            else:
                return "rollback" if state.get("_intent_type") == "rollback" else "extract_query"

        graph.add_conditional_edges(
            "classify_intent",
            hitl_disabled_router,
            {
                "rollback": "rollback",
                "extract_query": "extract_query"
            }
        )

    # Query processing flow
    graph.add_edge("extract_query", "text2sql")
    graph.add_edge("text2sql", "check_results")

    # check_results → conditional routing
    if enable_hitl:
        graph.add_conditional_edges(
            "check_results",
            route_after_results,
            {
                "ask_user": "ask_user",
                "visualization": "visualization",
                "build_response": "build_response"
            }
        )
    else:
        # HITL disabled: skip to visualization or response
        graph.add_conditional_edges(
            "check_results",
            lambda s: "build_response" if s.get("no_records_message") or s.get("error") else "visualization",
            {
                "visualization": "visualization",
                "build_response": "build_response"
            }
        )

    # Rollback → build_response
    graph.add_edge("rollback", "build_response")

    # Visualization → build_response
    graph.add_edge("visualization", "build_response")

    # build_response → END
    graph.add_edge("build_response", END)

    # -------------------------------------------------------------------------
    # COMPILE
    # -------------------------------------------------------------------------
    logger.info("[REPORT] Compiling graph...")

    # Setup checkpointer
    if checkpointer is None:
        checkpointer = MemorySaver()

    # Compile options
    compile_kwargs = {
        "checkpointer": checkpointer
    }

    # HITL interrupt configuration
    if enable_hitl:
        compile_kwargs["interrupt_before"] = ["ask_user"]
        logger.info("[REPORT] HITL enabled with interrupt_before=['ask_user']")

    compiled = graph.compile(**compile_kwargs)

    logger.info("[REPORT] Graph compiled successfully ✓")
    logger.info("[REPORT] Nodes: immediate_ack → classify_intent → [routing] → text2sql → visualization → build_response")

    return compiled


# =============================================================================
# HITL NODE IMPLEMENTATION
# =============================================================================

async def _ask_user_node(state: ReportState) -> dict:
    """
    HITL ask_user node.

    Bu node interrupt_before ile çalışır.
    Graph bu node'a geldiğinde durur ve kullanıcı input bekler.

    Resume edildiğinde, kullanıcı yanıtı state["user_clarification"]
    olarak gelir ve process_clarification node'u işler.
    """
    pending_question = state.get("pending_question")

    if not pending_question:
        logger.warning("[REPORT] ask_user called but no pending question")
        return {}

    # Format message for user
    message = format_interrupt_message(pending_question)
    logger.info(f"[REPORT] HITL: {message[:100]}...")

    # Graph burada durur (interrupt_before)
    # Kullanıcı yanıtı geldiğinde state["user_clarification"] ile resume edilir
    return {}


# =============================================================================
# LEGACY FUNCTION (backward compatibility)
# =============================================================================

def create_report_graph(text2sql_graph, visualization_graph):
    """
    Legacy function for backward compatibility.

    Deprecated: Use build_report_graph instead.
    """
    logger.warning("[REPORT] create_report_graph is deprecated, use build_report_graph")
    return build_report_graph(
        text2sql_graph=text2sql_graph,
        visualization_graph=visualization_graph,
        enable_hitl=False  # Legacy mode without HITL
    )
