"""
HITL Ambiguity Framework - Core Module

Unified ambiguity detection and management system for Human-In-The-Loop interactions.

Features:
- 5 ambiguity types (COLUMN, VALUE, CONTEXT, INTENT, PROMPT_SCOPE)
- Stage-aware detection (intent, metadata, results)
- Context-aware analysis
- Priority-based resolution

Author: Enhanced HITL System v2.0
Date: 2026-02-05
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Literal
from abc import ABC, abstractmethod


# =============================================================================
# AMBIGUITY TYPE ENUM - 5 distinct ambiguity categories
# =============================================================================

class AmbiguityType(str, Enum):
    """
    5 ambiguity types ordered by priority (highest to lowest).

    Priority determines which ambiguity to resolve first when multiple exist.
    """

    # Priority 1: Most critical - user query too vague
    PROMPT_SCOPE = "prompt_scope_ambiguity"

    # Priority 2: High risk - unclear if continuing previous context
    CONTEXT = "context_ambiguity"

    # Priority 3: Important - what does user want to do?
    INTENT = "intent_ambiguity"

    # Priority 4: Medium - which column to use?
    COLUMN = "column_ambiguity"

    # Priority 5: Low - which value to filter?
    VALUE = "value_ambiguity"


# =============================================================================
# AMBIGUITY CONTEXT - Complete ambiguity information
# =============================================================================

@dataclass
class AmbiguityContext:
    """
    Complete context for a detected ambiguity.

    This dataclass contains all information needed to:
    1. Build a user-friendly HITL question
    2. Process the user's clarification response
    3. Resume execution with resolved ambiguity

    Attributes:
        ambiguity_type: Type of ambiguity detected
        user_query: Original user query that triggered ambiguity
        active_context_summary: Summary of active query context (if exists)
        candidates: List of possible options (columns, values, intents, etc.)
        metadata: Additional type-specific metadata
        confidence_scores: Optional confidence scores for each candidate
        detection_stage: Where ambiguity was detected (intent, metadata, results)
        auto_resolvable: Whether this can be auto-resolved (confidence > 0.85)
    """

    # Core fields
    ambiguity_type: AmbiguityType
    user_query: str

    # Context information
    active_context_summary: Optional[str] = None

    # Candidates (options for user to choose from)
    candidates: List[Any] = field(default_factory=list)

    # Type-specific metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Confidence and resolution
    confidence_scores: Optional[Dict[str, float]] = None
    auto_resolvable: bool = False

    # Detection metadata
    detection_stage: Literal["intent", "metadata", "results", "prompt"] = "intent"

    def get_highest_confidence_candidate(self) -> Optional[tuple[Any, float]]:
        """
        Get candidate with highest confidence score.

        Returns:
            Tuple of (candidate, confidence) or None if no scores
        """
        if not self.confidence_scores or not self.candidates:
            return None

        # Find max confidence
        max_candidate = None
        max_confidence = 0.0

        for candidate in self.candidates:
            candidate_key = str(candidate)
            confidence = self.confidence_scores.get(candidate_key, 0.0)

            if confidence > max_confidence:
                max_confidence = confidence
                max_candidate = candidate

        return (max_candidate, max_confidence) if max_candidate else None

    def is_auto_resolvable(self, threshold: float = 0.85) -> bool:
        """
        Check if ambiguity can be auto-resolved.

        Args:
            threshold: Confidence threshold for auto-resolve (default 0.85)

        Returns:
            True if highest confidence exceeds threshold
        """
        result = self.get_highest_confidence_candidate()
        if not result:
            return False

        _, confidence = result
        return confidence >= threshold


# =============================================================================
# AMBIGUITY DETECTOR - Abstract base class
# =============================================================================

class AmbiguityDetector(ABC):
    """
    Abstract base class for ambiguity detection.

    Subclasses implement specific detection logic for each stage:
    - IntentAmbiguityDetector (classify_intent_node)
    - MetadataAmbiguityDetector (check_results_node)
    - PromptScopeDetector (classify_intent_node - for short queries)

    Usage:
        detector = IntentAmbiguityDetector()
        ambiguity = await detector.detect_ambiguity(state, stage="intent")

        if ambiguity:
            # Trigger HITL
            return await trigger_hitl(state, ambiguity)
    """

    @abstractmethod
    async def detect_ambiguity(
        self,
        state: Dict[str, Any],
        stage: Literal["intent", "metadata", "results", "prompt"]
    ) -> Optional[AmbiguityContext]:
        """
        Detect ambiguity in current state.

        Args:
            state: Current ReportState
            stage: Processing stage (intent, metadata, results, prompt)

        Returns:
            AmbiguityContext if ambiguity detected, None otherwise
        """
        pass

    def _get_active_context_summary(self, state: Dict[str, Any]) -> Optional[str]:
        """
        Extract and format active query context summary.

        Args:
            state: Current ReportState

        Returns:
            Human-readable context summary or None

        Example:
            "Ankara | Son 3 yıl | 125 satır"
        """
        context = state.get("active_query_context")
        if not context:
            return None

        # Extract key information
        filters = context.get("applied_filters", [])
        row_count = context.get("result_row_count", 0)

        # Build summary parts
        summary_parts = []

        # Add filters
        for f in filters[:3]:  # Max 3 filters in summary
            column = f.get("column", "")
            value = f.get("value", "")
            if column and value:
                summary_parts.append(f"{value}")

        # Add row count
        if row_count > 0:
            summary_parts.append(f"{row_count} satır")

        return " | ".join(summary_parts) if summary_parts else None

    def _has_context_reference(self, query: str) -> bool:
        """
        Check if query contains context reference words.

        Args:
            query: User query

        Returns:
            True if contains reference words like "burdaki", "bunun", "şu", etc.
        """
        query_lower = query.lower()

        reference_words = [
            "burdaki", "bunun", "bunlar", "bu", "şu", "o",
            "onun", "burada", "şurada", "orada",
            "yukardaki", "üstteki", "alttaki",
            "önceki", "son", "mevcut", "bu verilerde"
        ]

        return any(word in query_lower for word in reference_words)

    def _is_short_query(self, query: str, word_threshold: int = 3) -> bool:
        """
        Check if query is too short (potential prompt scope ambiguity).

        Args:
            query: User query
            word_threshold: Maximum word count to consider "short"

        Returns:
            True if query has <= word_threshold words
        """
        words = query.strip().split()
        return len(words) <= word_threshold


# =============================================================================
# AMBIGUITY TYPE-SPECIFIC METADATA BUILDERS
# =============================================================================

def build_context_ambiguity_metadata(
    state: Dict[str, Any],
    new_dimension: Optional[str] = None
) -> Dict[str, Any]:
    """
    Build metadata for context ambiguity.

    Args:
        state: Current ReportState
        new_dimension: Newly detected dimension (e.g., "category", "product")

    Returns:
        Metadata dict with filters, dimensions, etc.
    """
    context = state.get("active_query_context", {})

    return {
        "applied_filters": context.get("applied_filters", []),
        "grouping_columns": context.get("grouping_columns", []),
        "result_row_count": context.get("result_row_count", 0),
        "new_dimension": new_dimension,
        "has_context_reference": False,  # Will be set by detector
    }


def build_column_ambiguity_metadata(
    query_term: str,
    matched_columns: List[str],
    similarity_scores: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Build metadata for column ambiguity.

    Args:
        query_term: User's query term that matched multiple columns
        matched_columns: List of columns that matched
        similarity_scores: Optional similarity scores for each column

    Returns:
        Metadata dict
    """
    return {
        "query_term": query_term,
        "matched_columns": matched_columns,
        "similarity_scores": similarity_scores or {},
    }


def build_value_ambiguity_metadata(
    column: str,
    matched_values: List[str],
    similarity_scores: Optional[Dict[str, float]] = None,
    user_term: Optional[str] = None
) -> Dict[str, Any]:
    """
    Build metadata for value ambiguity.

    Args:
        column: Column name
        matched_values: List of values that matched
        similarity_scores: Optional similarity scores for each value
        user_term: User's original search term

    Returns:
        Metadata dict
    """
    return {
        "column": column,
        "matched_values": matched_values,
        "similarity_scores": similarity_scores or {},
        "user_term": user_term,
    }


def build_intent_ambiguity_metadata(
    possible_intents: List[str],
    confidence_scores: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """
    Build metadata for intent ambiguity.

    Args:
        possible_intents: List of possible intent types
        confidence_scores: Optional confidence scores for each intent

    Returns:
        Metadata dict
    """
    return {
        "possible_intents": possible_intents,
        "confidence_scores": confidence_scores or {},
    }


def build_prompt_scope_metadata(
    query: str,
    word_count: int,
    suggested_clarifications: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Build metadata for prompt scope ambiguity.

    Args:
        query: User query
        word_count: Number of words in query
        suggested_clarifications: Optional suggested clarifications

    Returns:
        Metadata dict
    """
    return {
        "query": query,
        "word_count": word_count,
        "suggested_clarifications": suggested_clarifications or [
            "Tüm kayıtları listele",
            "Özet istatistik göster",
            "Belirli bir filtre ile göster",
            "Gruplama ile göster"
        ],
    }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_filter_summary(filters: List[Dict[str, Any]], max_filters: int = 3) -> str:
    """
    Format applied filters for display in HITL questions.

    Args:
        filters: List of filter dicts
        max_filters: Maximum filters to show

    Returns:
        Formatted string (e.g., "Ankara, Son 3 yıl")
    """
    if not filters:
        return "Filtre yok"

    parts = []
    for f in filters[:max_filters]:
        value = f.get("value", "")
        if value:
            parts.append(str(value))

    result = ", ".join(parts)

    if len(filters) > max_filters:
        result += f" (+{len(filters) - max_filters} daha)"

    return result


def calculate_word_count(text: str) -> int:
    """
    Calculate word count for prompt scope detection.

    Args:
        text: Input text

    Returns:
        Word count
    """
    return len(text.strip().split())
