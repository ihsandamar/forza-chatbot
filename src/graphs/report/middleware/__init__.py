"""
Custom LangChain Middleware for Report Agent

This package contains custom middleware implementations for the
LangChain-based report agent.

Middleware:
- ContextManagementMiddleware: Active query context and history management
- MetadataCheckMiddleware: Metadata ambiguity detection and HITL
- IntentClassificationMiddleware: Context-aware intent classification
"""

from .context_management import (
    ContextManagementMiddleware,
    ContextManagementState,
    ActiveQueryContext,
    QueryCheckpoint
)
from .metadata_check import (
    MetadataCheckMiddleware,
    MetadataCheckState,
    PendingQuestion,
    format_hitl_question
)
from .intent_classification import (
    IntentClassificationMiddleware,
    IntentClassificationState,
    IntentType,
    IntentClassificationResult
)

__all__ = [
    # Context Management
    "ContextManagementMiddleware",
    "ContextManagementState",
    "ActiveQueryContext",
    "QueryCheckpoint",
    # Metadata Check
    "MetadataCheckMiddleware",
    "MetadataCheckState",
    "PendingQuestion",
    "format_hitl_question",
    # Intent Classification
    "IntentClassificationMiddleware",
    "IntentClassificationState",
    "IntentType",
    "IntentClassificationResult",
]
