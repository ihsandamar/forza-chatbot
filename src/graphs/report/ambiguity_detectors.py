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
    build_prompt_scope_metadata,
    build_query_type_metadata
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
        4. Query type ambiguity (if query type unclear - NEW!)

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

        # 4. Check query type ambiguity (Priority #3.5 - NEW!)
        query_type_ambiguity = self._detect_query_type_ambiguity(state)
        if query_type_ambiguity:
            logger.info("[AMBIGUITY] Query type ambiguity detected")
            return query_type_ambiguity

        return None

    def _detect_context_ambiguity(
        self,
        state: Dict[str, Any],
        user_query: str
    ) -> Optional[AmbiguityContext]:
        """
        Detect context ambiguity - CRITICAL for understanding user intent.

        ⚠️ AGGRESIVE DETECTION: Better to ask than assume!

        Detection criteria:
        1. Active context exists
        2. Context has filters OR grouping OR any previous state
        3. Query doesn't explicitly reference context ("burdaki", "bunun")
        4. Query is not a clear modification ("sadece", "ekle", "çıkar")
        5. Intent is new_query OR confidence < 0.8

        KEY PRINCIPLE: If there's ANY doubt about whether user wants to
        continue with context, ASK! This prevents major misunderstandings.

        Example 1 (MUST ASK):
            Context: Ankara + Son 3 yıl
            Query: "Hangi kategoriden satış olmuş?"
            → AMBIGUOUS! Ankara için mi, tüm veriler için mi? → ASK!

        Example 2 (MUST ASK):
            Context: Kategorilere göre satışlar
            Query: "Toplamları göster"
            → AMBIGUOUS! Mevcut kategoriler için mi, tüm veriler için mi? → ASK!

        Example 3 (NO AMBIGUITY):
            Context: Ankara
            Query: "Burdaki kategorilere göre göster"
            → CLEAR! "Burdaki" = context devam

        Args:
            state: Current ReportState
            user_query: User's query

        Returns:
            AmbiguityContext if ANY doubt exists, None only if crystal clear
        """
        # Check 1: Active context exists?
        context = state.get("active_query_context")
        if not context:
            return None

        # Check 2: Has filters OR grouping OR previous SQL?
        filters = context.get("applied_filters", [])
        grouping = context.get("grouping_columns", [])
        previous_sql = context.get("current_sql", "")

        # If no meaningful context, no ambiguity
        if not filters and not grouping and not previous_sql:
            return None

        # Check 3: Explicit context reference? (No ambiguity if user says "burdaki")
        if self._has_context_reference(user_query):
            return None

        # Check 4: Clear modification keywords? (No ambiguity if clear modification)
        modification_keywords = [
            "sadece", "için", "ekle", "çıkar", "filtrele",
            "değiştir", "kaldır", "sil", "ekleme"
        ]
        query_lower = user_query.lower()
        if any(kw in query_lower for kw in modification_keywords):
            # User is clearly modifying, not creating new query
            return None

        # Check 5: Intent and confidence
        intent_type = state.get("_intent_type", "")
        confidence = state.get("_confidence", 0.0)

        # CRITICAL: If intent is new_query OR low confidence → AMBIGUOUS!
        is_new_query = intent_type == "new_query"
        is_low_confidence = confidence < 0.8  # ⚠️ Lowered from 0.7 to 0.8 (more aggressive)

        if not is_new_query and not is_low_confidence:
            # Intent is clear modification with high confidence
            return None

        # Check 6: Query seems to ask for different analysis?
        # This includes ANY query that doesn't explicitly modify existing filters
        query_asks_for_analysis = any(word in query_lower for word in [
            "hangi", "ne kadar", "toplam", "ortalama", "maksimum",
            "minimum", "göster", "listele", "bul", "analiz"
        ])

        if not query_asks_for_analysis:
            # Query is not asking for analysis, might be clear modification
            return None

        # ⚠️ ALL CHECKS PASSED - CONTEXT AMBIGUITY DETECTED!
        # Better to ask than assume user's intent!

        logger.warning(
            f"[CONTEXT_AMBIGUITY] ⚠️ DETECTED! "
            f"Context has {len(filters)} filters, {len(grouping)} grouping. "
            f"Query: '{user_query}' - Intent: {intent_type}, Confidence: {confidence:.2f}"
        )

        # Detect what user might be asking about
        new_dimension = self._detect_new_dimension(user_query, context)

        # Build metadata
        metadata = build_context_ambiguity_metadata(
            state,
            new_dimension=new_dimension or "analiz"
        )
        metadata["has_context_reference"] = False
        metadata["user_query_type"] = "analysis_request"
        metadata["confidence"] = confidence

        # Get context summary
        context_summary = self._get_active_context_summary(state)

        logger.info(
            f"[CONTEXT_AMBIGUITY] Context summary: {context_summary}"
        )

        return AmbiguityContext(
            ambiguity_type=AmbiguityType.CONTEXT,
            user_query=user_query,
            active_context_summary=context_summary,
            candidates=["keep_context", "new_query"],
            metadata=metadata,
            detection_stage="intent",
            auto_resolvable=False  # ⚠️ NEVER auto-resolve context ambiguity!
        )

    def _detect_new_dimension(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> Optional[str]:
        """
        Detect if query mentions a dimension/metric.

        Args:
            query: User query
            context: Active query context

        Returns:
            Dimension name or "analiz" if general analysis
        """
        query_lower = query.lower()
        current_grouping = context.get("grouping_columns", [])

        # Dimension keywords (semantic analysis)
        dimension_keywords = {
            "kategori": "CategoryName",
            "ürün": "ProductName",
            "müşteri": "CustomerName",
            "şehir": "BranchCityName",
            "şube": "BranchName",
            "branch": "BranchName",
            "tarih": "DocumentDate",
            "ay": "DocumentDate",
            "yıl": "DocumentDate",
            "gün": "DocumentDate",
            "zaman": "DocumentDate",
            "dönem": "DocumentDate",
        }

        # Metric keywords (aggregation requests)
        metric_keywords = [
            "toplam", "tutar", "miktar", "adet", "sayı",
            "ortalama", "maksimum", "minimum", "en yüksek", "en düşük"
        ]

        # Check for dimension
        for keyword, column in dimension_keywords.items():
            if keyword in query_lower:
                # Check if not already in grouping
                if column not in current_grouping:
                    return keyword

        # Check for metric (aggregation request)
        for metric in metric_keywords:
            if metric in query_lower:
                return "toplam/analiz"

        # Check for analysis questions
        analysis_keywords = ["hangi", "ne kadar", "nasıl", "nerede", "kimden"]
        if any(kw in query_lower for kw in analysis_keywords):
            return "analiz"

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

    def _detect_query_type_ambiguity(
        self,
        state: Dict[str, Any]
    ) -> Optional[AmbiguityContext]:
        """
        Detect query type ambiguity - unclear which query type user wants.

        Detection criteria:
        1. Intent type is "new_query" (not modify/followup)
        2. Query type confidence < 0.65 (low confidence)
        3. Query could match multiple types (e.g., "Toplam ciro" → single_value or ranking)

        Examples of ambiguous queries:
        - "Toplam ciro" → single_value (total) or ranking (top products by revenue)?
        - "Satışlar" → aggregation (group by category) or single_value (total)?
        - "En çok satan" → ranking (top products) or single_value (max value)?

        Args:
            state: Current ReportState

        Returns:
            AmbiguityContext if detected, None otherwise
        """
        intent_type = state.get("_intent_type", "")
        query_type = state.get("query_type")
        query_type_confidence = state.get("query_type_confidence", 0.0)
        user_query = state.get("user_query", "")

        # Only check for new queries (not modifications)
        if intent_type != "new_query":
            return None

        # Check if query type confidence is low
        # ✅ Improved threshold: 0.7 (was 0.65) - less false positives
        if query_type_confidence >= 0.7:
            return None

        # Detect possible query types based on query patterns
        possible_types = self._detect_possible_query_types(user_query, query_type)

        # Need at least 2 possible types to have ambiguity
        if len(possible_types) < 2:
            return None

        logger.warning(
            f"[QUERY_TYPE_AMBIGUITY] ⚠️ DETECTED! "
            f"Query: '{user_query}' - Detected: {query_type} (conf: {query_type_confidence:.2f}), "
            f"Possible: {possible_types}"
        )

        # Build metadata
        metadata = build_query_type_metadata(
            query=user_query,
            possible_types=possible_types,
            detected_type=query_type,
            detection_confidence=query_type_confidence
        )

        context_summary = self._get_active_context_summary(state)

        return AmbiguityContext(
            ambiguity_type=AmbiguityType.QUERY_TYPE,
            user_query=user_query,
            active_context_summary=context_summary,
            candidates=possible_types,
            metadata=metadata,
            detection_stage="intent",
            auto_resolvable=False  # Never auto-resolve query type!
        )

    def _detect_possible_query_types(
        self,
        user_query: str,
        detected_type: Optional[str]
    ) -> List[str]:
        """
        Detect possible query types for ambiguous query.

        Args:
            user_query: User's query
            detected_type: Query type detected by LLM (if any)

        Returns:
            List of possible query types (2-4 types)
        """
        query_lower = user_query.lower()
        possible = []

        # Pattern 1: "Toplam X" → single_value OR ranking
        if any(kw in query_lower for kw in ["toplam", "toplamı", "kaç", "ne kadar"]):
            # Could be single value OR could want top-N
            if "en" not in query_lower:  # "en çok" means ranking
                possible.extend(["single_value", "aggregation"])
                if any(kw in query_lower for kw in ["göre", "bazlı", "dağılım"]):
                    possible.append("distribution")

        # Pattern 2: "En çok/az X" → ranking OR single_value (max/min)
        if any(kw in query_lower for kw in ["en çok", "en az", "en yüksek", "en düşük"]):
            possible.append("ranking")
            # Could also want single max value
            if not any(num_kw in query_lower for num_kw in ["10", "5", "3", "ilk", "top"]):
                possible.append("single_value")

        # Pattern 3: Generic aggregation → multiple interpretations
        if any(kw in query_lower for kw in ["satış", "ciro", "miktar"]) and len(query_lower.split()) <= 3:
            if "toplam" not in query_lower and "en" not in query_lower:
                possible.extend(["single_value", "aggregation", "ranking"])

        # Pattern 4: "X göre Y" → aggregation OR distribution
        if "göre" in query_lower or "bazlı" in query_lower or "bazında" in query_lower:
            possible.extend(["aggregation", "distribution"])

        # Remove duplicates and limit to 4
        possible = list(dict.fromkeys(possible))[:4]

        # Ensure detected type is included if exists
        if detected_type and detected_type not in possible:
            possible.insert(0, detected_type)

        # If we have < 2 types, no ambiguity
        if len(possible) < 2:
            return []

        return possible[:4]  # Max 4 options


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
