"""
Ambiguity Detectors - Stage-specific detection implementations

Implements detection logic for each ambiguity type at different stages:
- IntentStageDetector: Detects ambiguities during intent classification
- MetadataStageDetector: Detects ambiguities during metadata resolution
- PromptScopeDetector: Detects short/vague queries

Author: Enhanced HITL System v2.0
Date: 2026-02-05
"""

import logging
from typing import Dict, Any, Optional, List, Literal
from .ambiguity_framework import (
    AmbiguityDetector,
    AmbiguityContext,
    AmbiguityType,
    build_context_ambiguity_metadata,
    build_column_ambiguity_metadata,
    build_value_ambiguity_metadata,
    build_intent_ambiguity_metadata,
    build_prompt_scope_metadata
)

logger = logging.getLogger(__name__)


# =============================================================================
# INTENT STAGE DETECTOR - Detects ambiguities during intent classification
# =============================================================================

class IntentStageDetector(AmbiguityDetector):
    """
    Detects ambiguities at the intent classification stage.

    Checks for:
    1. Context ambiguity (most critical)
    2. Prompt scope ambiguity (short queries)
    3. Intent ambiguity (unclear what user wants)

    Usage:
        detector = IntentStageDetector()
        ambiguity = await detector.detect_ambiguity(state, stage="intent")
    """

    async def detect_ambiguity(
        self,
        state: Dict[str, Any],
        stage: Literal["intent", "metadata", "results", "prompt"]
    ) -> Optional[AmbiguityContext]:
        """
        Detect ambiguity at intent classification stage.

        Priority order:
        1. Prompt scope (if query too short)
        2. Context ambiguity (if context exists and unclear if continuing)
        3. Intent ambiguity (if intent classification confidence low)

        Args:
            state: Current ReportState
            stage: Processing stage (should be "intent")

        Returns:
            First detected ambiguity (highest priority) or None
        """
        # Infinite loop protection
        clarification_count = state.get("clarification_count", 0)
        if clarification_count >= 3:
            logger.warning("[AMBIGUITY] Max clarification count reached, skipping detection")
            return None

        user_query = state.get("user_query", "")
        if not user_query:
            return None

        # 1. Check prompt scope (Priority #1)
        prompt_scope_ambiguity = await self._detect_prompt_scope(state, user_query)
        if prompt_scope_ambiguity:
            logger.info("[AMBIGUITY] Prompt scope ambiguity detected")
            return prompt_scope_ambiguity

        # 2. Check context ambiguity (Priority #2)
        context_ambiguity = self._detect_context_ambiguity(state, user_query)
        if context_ambiguity:
            logger.info("[AMBIGUITY] Context ambiguity detected")
            return context_ambiguity

        # 3. Check intent ambiguity (Priority #3)
        intent_ambiguity = self._detect_intent_ambiguity(state)
        if intent_ambiguity:
            logger.info("[AMBIGUITY] Intent ambiguity detected")
            return intent_ambiguity

        return None

    def _detect_context_ambiguity(
        self,
        state: Dict[str, Any],
        user_query: str
    ) -> Optional[AmbiguityContext]:
        """
        Detect context ambiguity - unclear if user wants to continue with filters.

        Detection criteria (ALL must be true):
        1. Active context exists
        2. Context has filters applied
        3. New dimension detected (different from current grouping)
        4. No explicit context reference ("burdaki", "bunun", etc.)
        5. Intent classified as new_query

        Example:
            Context: Ankara + Son 3 yıl
            Query: "Hangi kategoriden satış olmuş?"
            → Ambiguous: Ankara için mi, tüm veriler için mi?

        Args:
            state: Current ReportState
            user_query: User's query

        Returns:
            AmbiguityContext if detected, None otherwise
        """
        # Check 1: Active context exists?
        context = state.get("active_query_context")
        if not context:
            return None

        # Check 2: Has filters?
        filters = context.get("applied_filters", [])
        if not filters:
            return None

        # Check 3: Intent is new_query?
        intent_type = state.get("_intent_type", "")
        if intent_type != "new_query":
            return None

        # Check 4: No context reference?
        if self._has_context_reference(user_query):
            return None

        # Check 5: New dimension detected?
        # Extract entities from state
        extracted_entities = state.get("_extracted_entities", {})
        new_dimension = extracted_entities.get("new_dimension")

        # If no explicit new_dimension, try to detect from query
        if not new_dimension:
            new_dimension = self._detect_new_dimension(user_query, context)

        if not new_dimension:
            return None

        # All criteria met - context ambiguity detected!
        logger.info(
            f"[CONTEXT_AMBIGUITY] Detected: filters={len(filters)}, "
            f"new_dimension={new_dimension}, no_reference=True"
        )

        # Build metadata
        metadata = build_context_ambiguity_metadata(
            state,
            new_dimension=new_dimension
        )
        metadata["has_context_reference"] = False

        # Get context summary
        context_summary = self._get_active_context_summary(state)

        return AmbiguityContext(
            ambiguity_type=AmbiguityType.CONTEXT,
            user_query=user_query,
            active_context_summary=context_summary,
            candidates=["keep_filters", "clear_filters"],
            metadata=metadata,
            detection_stage="intent",
            auto_resolvable=False  # Always ask user for context ambiguity
        )

    def _detect_new_dimension(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> Optional[str]:
        """
        Detect if query mentions a new dimension not in current grouping.

        Args:
            query: User query
            context: Active query context

        Returns:
            New dimension name (e.g., "kategori", "ürün") or None
        """
        query_lower = query.lower()
        current_grouping = context.get("grouping_columns", [])

        # Dimension keywords
        dimension_keywords = {
            "kategori": "CategoryName",
            "ürün": "ProductName",
            "müşteri": "CustomerName",
            "şehir": "BranchCityName",
            "şube": "BranchName",
            "tarih": "DocumentDate",
            "ay": "DocumentDate",
            "yıl": "DocumentDate",
        }

        for keyword, column in dimension_keywords.items():
            if keyword in query_lower:
                # Check if not already in grouping
                if column not in current_grouping:
                    return keyword

        return None

    async def _detect_prompt_scope(
        self,
        state: Dict[str, Any],
        user_query: str
    ) -> Optional[AmbiguityContext]:
        """
        Detect prompt scope ambiguity - query too short/vague.

        Detection criteria:
        1. Query has <= 3 words
        2. No active context (or context is minimal)
        3. LLM confirms query is too vague (optional, for now use heuristic)

        Example:
            Query: "Satışlar"
            → Too vague: list all? summary stats? filtered? grouped?

        Args:
            state: Current ReportState
            user_query: User's query

        Returns:
            AmbiguityContext if detected, None otherwise
        """
        # Check 1: Query too short?
        if not self._is_short_query(user_query, word_threshold=3):
            return None

        # Check 2: No context or minimal context?
        context = state.get("active_query_context")
        if context and context.get("applied_filters"):
            # Has context, short query might be modification
            return None

        # Prompt scope ambiguity detected!
        logger.info(f"[PROMPT_SCOPE] Short query detected: '{user_query}'")

        # Build metadata
        word_count = len(user_query.strip().split())
        metadata = build_prompt_scope_metadata(
            query=user_query,
            word_count=word_count
        )

        return AmbiguityContext(
            ambiguity_type=AmbiguityType.PROMPT_SCOPE,
            user_query=user_query,
            active_context_summary=None,
            candidates=metadata["suggested_clarifications"],
            metadata=metadata,
            detection_stage="prompt",
            auto_resolvable=False
        )

    def _detect_intent_ambiguity(
        self,
        state: Dict[str, Any]
    ) -> Optional[AmbiguityContext]:
        """
        Detect intent ambiguity - unclear what user wants to do.

        Detection criteria:
        1. Intent classification confidence < 0.7
        2. Multiple possible intents with similar scores

        Args:
            state: Current ReportState

        Returns:
            AmbiguityContext if detected, None otherwise
        """
        confidence = state.get("_confidence", 1.0)
        intent_type = state.get("_intent_type")

        # Check confidence threshold
        if confidence >= 0.7:
            return None

        # If no intent type detected
        if not intent_type or intent_type == "unknown":
            logger.info("[INTENT_AMBIGUITY] Unknown intent detected")

            # Build possible intents list
            possible_intents = ["new_query", "modify_filter"]

            metadata = build_intent_ambiguity_metadata(
                possible_intents=possible_intents
            )

            context_summary = self._get_active_context_summary(state)

            return AmbiguityContext(
                ambiguity_type=AmbiguityType.INTENT,
                user_query=state.get("user_query", ""),
                active_context_summary=context_summary,
                candidates=possible_intents,
                metadata=metadata,
                detection_stage="intent",
                auto_resolvable=False
            )

        return None


# =============================================================================
# METADATA STAGE DETECTOR - Detects column/value ambiguities
# =============================================================================

class MetadataStageDetector(AmbiguityDetector):
    """
    Detects ambiguities at the metadata resolution stage.

    Checks for:
    1. Column ambiguity (multiple columns match query term)
    2. Value ambiguity (multiple values match query term)

    Usage:
        detector = MetadataStageDetector()
        ambiguity = await detector.detect_ambiguity(state, stage="metadata")
    """

    async def detect_ambiguity(
        self,
        state: Dict[str, Any],
        stage: Literal["intent", "metadata", "results", "prompt"]
    ) -> Optional[AmbiguityContext]:
        """
        Detect ambiguity at metadata resolution stage.

        Priority order:
        1. Column ambiguity
        2. Value ambiguity

        Args:
            state: Current ReportState
            stage: Processing stage (should be "metadata")

        Returns:
            First detected ambiguity or None
        """
        # Infinite loop protection
        clarification_count = state.get("clarification_count", 0)
        if clarification_count >= 3:
            logger.warning("[AMBIGUITY] Max clarification count reached, skipping detection")
            return None

        # Check for ambiguities stored in state
        # (These are detected by value_resolver or metadata services)

        # Column ambiguity
        column_ambiguity = self._detect_column_ambiguity(state)
        if column_ambiguity:
            logger.info("[AMBIGUITY] Column ambiguity detected")
            return column_ambiguity

        # Value ambiguity
        value_ambiguity = self._detect_value_ambiguity(state)
        if value_ambiguity:
            logger.info("[AMBIGUITY] Value ambiguity detected")
            return value_ambiguity

        return None

    def _detect_column_ambiguity(
        self,
        state: Dict[str, Any]
    ) -> Optional[AmbiguityContext]:
        """
        Detect column ambiguity from state.

        Expects state to have:
        - enriched_metadata with multiple matching columns

        Args:
            state: Current ReportState

        Returns:
            AmbiguityContext if detected, None otherwise
        """
        # Check if metadata has column ambiguity marker
        enriched_metadata = state.get("enriched_metadata", {})
        ambiguous_columns = enriched_metadata.get("ambiguous_columns")

        if not ambiguous_columns or len(ambiguous_columns) <= 1:
            return None

        # Extract query term
        query_term = enriched_metadata.get("query_term", "belirtilen terim")

        # Build metadata
        metadata = build_column_ambiguity_metadata(
            query_term=query_term,
            matched_columns=ambiguous_columns
        )

        context_summary = self._get_active_context_summary(state)

        return AmbiguityContext(
            ambiguity_type=AmbiguityType.COLUMN,
            user_query=state.get("user_query", ""),
            active_context_summary=context_summary,
            candidates=ambiguous_columns,
            metadata=metadata,
            detection_stage="metadata",
            auto_resolvable=False
        )

    def _detect_value_ambiguity(
        self,
        state: Dict[str, Any]
    ) -> Optional[AmbiguityContext]:
        """
        Detect value ambiguity from state.

        Expects state to have:
        - enriched_metadata with multiple matching values

        Args:
            state: Current ReportState

        Returns:
            AmbiguityContext if detected, None otherwise
        """
        # Check if metadata has value ambiguity marker
        enriched_metadata = state.get("enriched_metadata", {})
        ambiguous_values = enriched_metadata.get("ambiguous_values")

        if not ambiguous_values or len(ambiguous_values) <= 1:
            return None

        # Extract context
        column = enriched_metadata.get("column", "")
        user_term = enriched_metadata.get("user_term", "")
        similarity_scores = enriched_metadata.get("similarity_scores", {})

        # Build metadata
        metadata = build_value_ambiguity_metadata(
            column=column,
            matched_values=ambiguous_values,
            similarity_scores=similarity_scores,
            user_term=user_term
        )

        # Check if auto-resolvable (high confidence)
        confidence_scores = {
            str(val): similarity_scores.get(str(val), 0.0)
            for val in ambiguous_values
        }

        context_summary = self._get_active_context_summary(state)

        ambiguity_ctx = AmbiguityContext(
            ambiguity_type=AmbiguityType.VALUE,
            user_query=state.get("user_query", ""),
            active_context_summary=context_summary,
            candidates=ambiguous_values,
            metadata=metadata,
            confidence_scores=confidence_scores,
            detection_stage="metadata",
            auto_resolvable=False
        )

        # Check if auto-resolvable
        ambiguity_ctx.auto_resolvable = ambiguity_ctx.is_auto_resolvable(threshold=0.85)

        return ambiguity_ctx


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def create_intent_detector() -> IntentStageDetector:
    """Factory function for intent stage detector."""
    return IntentStageDetector()


def create_metadata_detector() -> MetadataStageDetector:
    """Factory function for metadata stage detector."""
    return MetadataStageDetector()
