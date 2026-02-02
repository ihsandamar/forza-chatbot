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
try:
    from langgraph.types import interrupt, Command
    HAS_INTERRUPT = True
except ImportError:
    # Fallback for older LangGraph versions
    HAS_INTERRUPT = False
    interrupt = None
    Command = None

from src.models.llm import LLM

from .state import ReportState
from .nodes import (
    immediate_acknowledgment_node,
    create_intent_classifier_node,
    process_user_clarification_node,
    extract_query_node,
    check_results_node,
    decide_visualization_node,
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

    # Visualization decision (moved from data_visualization graph)
    graph.add_node("decide_visualization", decide_visualization_node)

    # Rollback
    graph.add_node("rollback", rollback_node)

    # Visualization rendering (only renders, no decision)
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
                "visualize_direct": "decide_visualization",  # Skip text2sql for chart conversion
                "process_query": "extract_query"
            }
        )

        # HITL flow
        graph.add_edge("ask_user", "process_clarification")
        graph.add_edge("process_clarification", "extract_query")
    else:
        # HITL disabled: use smart router but skip ask_user
        async def hitl_disabled_router(state: ReportState) -> str:
            """HITL disabled router."""
            if llm:
                route = await smart_router(state)
                if route == "ask_user":
                    return "extract_query"
                return route  # rollback, visualize_direct, or extract_query
            else:
                intent = state.get("_intent_type", "new_query")
                if intent == "rollback":
                    return "rollback"
                elif intent == "visualize":
                    return "visualize_direct"
                else:
                    return "extract_query"

        graph.add_conditional_edges(
            "classify_intent",
            hitl_disabled_router,
            {
                "rollback": "rollback",
                "visualize_direct": "decide_visualization",
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
                "decide_visualization": "decide_visualization",  # Go to viz decision first
                "build_response": "build_response"
            }
        )
    else:
        # HITL disabled: skip to viz decision or response
        graph.add_conditional_edges(
            "check_results",
            lambda s: "build_response" if s.get("no_records_message") or s.get("error") else "decide_visualization",
            {
                "decide_visualization": "decide_visualization",
                "build_response": "build_response"
            }
        )

    # decide_visualization → conditional routing (check needs_graph)
    def route_after_viz_decision(state: ReportState) -> str:
        """Route based on needs_graph decision."""
        viz_decision = state.get("_viz_decision", {})
        needs_graph = viz_decision.get("needs_graph", False)

        if needs_graph:
            logger.info("[REPORT] Routing to visualization (graph needed)")
            return "visualization"
        else:
            logger.info("[REPORT] Skipping visualization (no graph needed)")
            return "build_response"

    graph.add_conditional_edges(
        "decide_visualization",
        route_after_viz_decision,
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

    # HITL configuration - NO interrupt_before (using command-based pattern)
    if enable_hitl:
        if HAS_INTERRUPT:
            logger.info("[REPORT] HITL enabled with interrupt() command-based pattern")
        else:
            logger.warning("[REPORT] interrupt() not available, using message-based HITL")

    compiled = graph.compile(**compile_kwargs)

    logger.info("[REPORT] Graph compiled successfully ✓")
    logger.info("[REPORT] Nodes: immediate_ack → classify_intent → [routing] → text2sql → visualization → build_response")

    return compiled


# =============================================================================
# HITL NODE IMPLEMENTATION
# =============================================================================

async def _ask_user_node(state: ReportState) -> dict:
    """
    HITL ask_user node - Command-based pattern.

    Bu node interrupt() kullanarak kullanıcı input'u bekler.
    interrupt_before yerine, node içinde interrupt() çağrılır.

    Kullanıcı Command(resume=...) ile cevap verir.
    """
    pending_question = state.get("pending_question")

    if not pending_question:
        logger.warning("[REPORT] ask_user called but no pending question")
        return {}

    # Format message for user
    message = format_interrupt_message(pending_question)
    logger.info(f"[REPORT] HITL question: {message[:100]}...")

    # Command-based HITL pattern
    if HAS_INTERRUPT and interrupt:
        # Use interrupt() to pause and wait for user input via Command(resume=...)
        logger.info("[REPORT] Using interrupt() for command-based HITL")
        user_response = interrupt(message)
        logger.info(f"[REPORT] User response received via interrupt: {user_response}")

        # Set user_clarification with the response
        return {
            "user_clarification": user_response,
            "pending_question": None,
            "waiting_for_user_input": False
        }
    else:
        # Fallback: Message-based HITL (old pattern)
        # Graph will return to user, expecting next message as clarification
        logger.info("[REPORT] Using message-based HITL (fallback)")

        # Add HITL question as AI message
        from langchain_core.messages import AIMessage
        return {
            "messages": [AIMessage(content=message)],
            "waiting_for_user_input": True
        }


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
