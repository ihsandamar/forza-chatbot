"""
Report Graph Package

Stateful Report Agent - HITL destekli, context-aware rapor üretim sistemi.

Components:
- state: State tanımları (ReportState, ActiveQueryContext, QueryCheckpoint)
- intent: Intent classification (IntentType, IntentClassifier)
- tools: HITL tools (ask_user_clarification, HITLQuestions)
- nodes: Node fonksiyonları
- graph: Graph builder (build_report_graph)
"""

from .state import (
    ReportState,
    ActiveQueryContext,
    QueryCheckpoint,
    PendingQuestion,
    create_empty_context,
    create_checkpoint,
    create_initial_state
)

from .intent import (
    IntentType,
    IntentClassification,
    IntentClassifier,
    SimpleIntentClassifier
)

from .tools import (
    ask_user_clarification,
    HITLQuestions,
    should_interrupt,
    format_interrupt_message,
    create_clarification_request
)

from .graph import (
    build_report_graph,
    create_report_graph  # Legacy
)

__all__ = [
    # State
    "ReportState",
    "ActiveQueryContext",
    "QueryCheckpoint",
    "PendingQuestion",
    "create_empty_context",
    "create_checkpoint",
    "create_initial_state",

    # Intent
    "IntentType",
    "IntentClassification",
    "IntentClassifier",
    "SimpleIntentClassifier",

    # Tools
    "ask_user_clarification",
    "HITLQuestions",
    "should_interrupt",
    "format_interrupt_message",
    "create_clarification_request",

    # Graph
    "build_report_graph",
    "create_report_graph",
]
