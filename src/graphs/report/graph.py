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
    route_after_results,
    # LLM-enhanced factories
    create_conversation_aware_intent_node,
    create_business_insights_node,
    create_llm_viz_decision_node,
    create_natural_response_node,
    # Phase 1 optimization
    create_parallel_insights_viz_node
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
    enable_llm_conversation: bool = True,
    enable_business_insights: bool = True,
    enable_llm_interpretation: bool = True,
    enable_natural_response: bool = True,
    enable_semantic_cache: bool = True,  # OPTIMIZATION: Enable by default for Phase 1
    checkpointer=None,
    config_schema=None
) -> StateGraph:
    """
    Build the stateful report generation graph with LLM-driven architecture.

    Args:
        text2sql_graph: Compiled text2sql graph
        visualization_graph: Compiled visualization graph
        llm: Language model for intent classification (optional)
        enable_hitl: Enable HITL features (interrupt_before)
        enable_llm_conversation: Enable LLM-powered conversation management
        enable_business_insights: Enable business insights extraction
        enable_llm_interpretation: Enable LLM-powered visualization interpretation
        enable_natural_response: Enable natural language response generation
        enable_semantic_cache: Enable semantic caching for LLM calls (opt-in, adds embedding cost)
        checkpointer: State checkpointer (default: MemorySaver)
        config_schema: Configuration schema for runtime config (optional)
                      If not provided, uses GenericSQLAssistantConfiguration

    Returns:
        Compiled StateGraph with optional LLM-driven enhancements
    """
    logger.info("[REPORT] Building stateful report graph...")
    logger.info(f"[REPORT] Feature flags: llm_conversation={enable_llm_conversation}, "
                f"business_insights={enable_business_insights}, "
                f"llm_interpretation={enable_llm_interpretation}, "
                f"natural_response={enable_natural_response}, "
                f"semantic_cache={enable_semantic_cache}")

    # Import config schema if not provided
    if config_schema is None:
        from src.graphs.generic_text2sql.assistant_configuration import GenericSQLAssistantConfiguration
        config_schema = GenericSQLAssistantConfiguration

    # Create graph with enhanced state and config schema
    graph = StateGraph(ReportState, config_schema=config_schema)

    # Create node factories
    text2sql_node = create_text2sql_node(text2sql_graph)
    visualization_node = create_visualization_node(visualization_graph)

    # =========================================================================
    # INITIALIZE LLM-DRIVEN COMPONENTS (if enabled)
    # =========================================================================
    semantic_cache = None
    conversation_manager = None
    business_context_tracker = None
    report_interpreter = None
    response_generator = None

    if llm:
        llm_chat = llm.get_chat()

        # Semantic Cache (opt-in, requires embeddings)
        if enable_semantic_cache:
            try:
                from .semantic_cache import SemanticCache
                # Try to get embeddings from LLM
                if hasattr(llm, 'get_embeddings'):
                    embeddings = llm.get_embeddings()
                    semantic_cache = SemanticCache(
                        embeddings=embeddings,
                        threshold=0.95,
                        ttl=3600,
                        max_size=2000  # OPTIMIZATION: Increased from 1000 to 2000 for Phase 1
                    )
                    logger.info("[REPORT] Semantic cache enabled with max_size=2000")
                else:
                    logger.warning("[REPORT] Semantic cache requested but embeddings not available")
            except Exception as e:
                logger.warning(f"[REPORT] Semantic cache initialization failed: {e}")

        # ConversationManager
        if enable_llm_conversation:
            from .conversation_manager import create_conversation_manager
            conversation_manager = create_conversation_manager(
                llm=llm_chat,
                enable_llm_reasoning=True,
                semantic_cache=semantic_cache
            )
            logger.info("[REPORT] ConversationManager enabled")

        # BusinessContextTracker
        if enable_business_insights:
            from .business_context_tracker import BusinessContextTracker
            business_context_tracker = BusinessContextTracker(
                llm=llm_chat,
                semantic_cache=semantic_cache
            )
            logger.info("[REPORT] BusinessContextTracker enabled")

        # ReportInterpreter
        if enable_llm_interpretation:
            from .report_interpreter import create_report_interpreter
            report_interpreter = create_report_interpreter(
                llm=llm_chat,
                use_llm=True,
                semantic_cache=semantic_cache
            )
            logger.info("[REPORT] ReportInterpreter enabled")

        # ResponseGenerator
        if enable_natural_response:
            from .response_generator import create_response_generator
            response_generator = create_response_generator(
                llm=llm_chat,
                use_llm=True,
                semantic_cache=semantic_cache
            )
            logger.info("[REPORT] ResponseGenerator enabled")

    # =========================================================================
    # CREATE NODE FUNCTIONS (with factory pattern)
    # =========================================================================

    # Intent classifier node
    if llm and enable_llm_conversation and conversation_manager:
        # Use LLM-powered ConversationManager
        intent_classifier_node = create_conversation_aware_intent_node(conversation_manager)
        logger.info("[REPORT] Using ConversationManager for intent understanding")
    elif llm:
        # Use existing IntentClassifier
        llm_chat = llm.get_chat()
        intent_classifier_node = create_intent_classifier_node(llm_chat)
        logger.info("[REPORT] Using IntentClassifier (standard)")
    else:
        # Fallback: simple classifier (LLM olmadan)
        async def simple_intent_node(state: ReportState):
            return {"_intent_type": "new_query", "_confidence": 0.8}
        intent_classifier_node = simple_intent_node
        logger.info("[REPORT] Using simple rule-based classifier (no LLM)")

    # Business insights extraction node
    if business_context_tracker:
        business_insights_node = create_business_insights_node(business_context_tracker)
        logger.info("[REPORT] Business insights node created")
    else:
        # No-op node
        async def noop_insights_node(state: ReportState):
            return {}
        business_insights_node = noop_insights_node

    # Visualization decision node
    if report_interpreter:
        viz_decision_node = create_llm_viz_decision_node(report_interpreter)
        logger.info("[REPORT] Using LLM-powered visualization decision")
    else:
        viz_decision_node = decide_visualization_node
        logger.info("[REPORT] Using rule-based visualization decision")

    # Response generation node
    if response_generator:
        response_node = create_natural_response_node(response_generator)
        logger.info("[REPORT] Using natural language response generation")
    else:
        response_node = build_response_node
        logger.info("[REPORT] Using template-based response generation")

    # Router
    if llm:
        llm_chat = llm.get_chat()
        smart_router = create_route_after_intent(llm_chat)
        logger.info("[REPORT] Using LLM-based smart router")
    else:
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

    # Business insights extraction (LLM-driven)
    if business_context_tracker:
        graph.add_node("extract_business_insights", business_insights_node)

    # Visualization decision (LLM-driven or rule-based)
    graph.add_node("decide_visualization", viz_decision_node)

    # Rollback
    graph.add_node("rollback", rollback_node)

    # Visualization rendering (only renders, no decision)
    graph.add_node("visualization", visualization_node)

    # Response generation (natural language or template-based)
    graph.add_node("build_response", response_node)

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

    # check_results → conditional routing (with business insights if enabled)
    # =========================================================================
    # PHASE 1 OPTIMIZATION: PARALLEL INSIGHTS + VIZ DECISION
    # =========================================================================
    if enable_hitl:
        if business_context_tracker and enable_llm_interpretation:
            # PARALLEL MODE: Both business insights and viz decision enabled
            logger.info("[REPORT] ⚡ Using PARALLEL insights + viz decision mode")

            # Create parallel node
            parallel_node = create_parallel_insights_viz_node(
                business_tracker=business_context_tracker,
                report_interpreter=report_interpreter
            )
            graph.add_node("parallel_insights_viz", parallel_node)

            # Wire: check_results → parallel_insights_viz → decide_visualization
            graph.add_conditional_edges(
                "check_results",
                route_after_results,
                {
                    "ask_user": "ask_user",
                    "decide_visualization": "parallel_insights_viz",  # Changed to parallel node
                    "build_response": "build_response"
                }
            )
            # After parallel node, go to decide_visualization (for routing only)
            # The decision is already made in parallel, this node just routes
            graph.add_edge("parallel_insights_viz", "decide_visualization")

        elif business_context_tracker:
            # SEQUENTIAL MODE: Only business insights enabled
            logger.info("[REPORT] Using sequential insights mode (viz decision disabled)")
            graph.add_conditional_edges(
                "check_results",
                route_after_results,
                {
                    "ask_user": "ask_user",
                    "decide_visualization": "extract_business_insights",  # Extract insights first
                    "build_response": "build_response"
                }
            )
            # Then go to viz decision
            graph.add_edge("extract_business_insights", "decide_visualization")
        else:
            # Without business insights
            graph.add_conditional_edges(
                "check_results",
                route_after_results,
                {
                    "ask_user": "ask_user",
                    "decide_visualization": "decide_visualization",
                    "build_response": "build_response"
                }
            )
    else:
        # HITL disabled
        if business_context_tracker and enable_llm_interpretation:
            # PARALLEL MODE: Both business insights and viz decision enabled
            logger.info("[REPORT] ⚡ Using PARALLEL insights + viz decision mode (HITL disabled)")

            # Create parallel node
            parallel_node = create_parallel_insights_viz_node(
                business_tracker=business_context_tracker,
                report_interpreter=report_interpreter
            )
            graph.add_node("parallel_insights_viz", parallel_node)

            # Wire: check_results → parallel_insights_viz → decide_visualization
            graph.add_conditional_edges(
                "check_results",
                lambda s: "build_response" if s.get("no_records_message") or s.get("error") else "parallel_insights_viz",
                {
                    "parallel_insights_viz": "parallel_insights_viz",
                    "build_response": "build_response"
                }
            )
            graph.add_edge("parallel_insights_viz", "decide_visualization")

        elif business_context_tracker:
            # SEQUENTIAL MODE: Only business insights enabled
            logger.info("[REPORT] Using sequential insights mode (viz decision disabled, HITL disabled)")
            graph.add_conditional_edges(
                "check_results",
                lambda s: "build_response" if s.get("no_records_message") or s.get("error") else "extract_business_insights",
                {
                    "extract_business_insights": "extract_business_insights",
                    "build_response": "build_response"
                }
            )
            graph.add_edge("extract_business_insights", "decide_visualization")
        else:
            # Without business insights
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
