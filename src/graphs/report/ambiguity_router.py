"""
Ambiguity Router - Priority-based ambiguity selection and fallback

Handles multiple concurrent ambiguities by:
1. Priority-based selection (PROMPT_SCOPE > CONTEXT > INTENT > COLUMN > VALUE)
2. Auto-resolution for high-confidence cases
3. Fallback strategies when ambiguity unresolved

Features:
- Priority ordering
- Auto-resolve for value ambiguity (confidence > 0.85)
- Default context resolution (keep filters by default)
- Infinite loop protection

Author: Enhanced HITL System v2.0
Date: 2026-02-05
"""

import logging
from typing import List, Optional, Dict, Any
from .ambiguity_framework import (
    AmbiguityContext,
    AmbiguityType
)

logger = logging.getLogger(__name__)


# =============================================================================
# AMBIGUITY ROUTER - Priority-based selection
# =============================================================================

class AmbiguityRouter:
    """
    Routes multiple ambiguities to highest priority one.

    Priority order (highest to lowest):
    1. PROMPT_SCOPE - Query too vague, must clarify intent
    2. CONTEXT - High risk of misinterpretation
    3. INTENT - Important to understand what user wants
    4. COLUMN - Medium importance, metadata level
    5. VALUE - Lowest, often auto-resolvable

    Usage:
        ambiguities = [context_ambiguity, value_ambiguity]
        selected = AmbiguityRouter.select_ambiguity(ambiguities)
        # Returns context_ambiguity (higher priority)
    """

    # Priority order (index = priority, lower index = higher priority)
    PRIORITY_ORDER = [
        AmbiguityType.PROMPT_SCOPE,    # 0 - Highest
        AmbiguityType.CONTEXT,         # 1
        AmbiguityType.INTENT,          # 2
        AmbiguityType.COLUMN,          # 3
        AmbiguityType.VALUE            # 4 - Lowest
    ]

    @classmethod
    def select_ambiguity(
        cls,
        ambiguities: List[AmbiguityContext]
    ) -> Optional[AmbiguityContext]:
        """
        Select highest priority ambiguity from list.

        Args:
            ambiguities: List of detected ambiguities

        Returns:
            Highest priority ambiguity or None if list empty

        Example:
            ambiguities = [
                AmbiguityContext(type=CONTEXT, ...),
                AmbiguityContext(type=VALUE, ...),
            ]
            selected = AmbiguityRouter.select_ambiguity(ambiguities)
            # Returns CONTEXT ambiguity (higher priority)
        """
        if not ambiguities:
            return None

        # Sort by priority
        sorted_ambiguities = sorted(
            ambiguities,
            key=lambda a: cls._get_priority(a.ambiguity_type)
        )

        selected = sorted_ambiguities[0]

        logger.info(
            f"[AMBIGUITY_ROUTER] Selected {selected.ambiguity_type} "
            f"from {len(ambiguities)} ambiguities"
        )

        return selected

    @classmethod
    def _get_priority(cls, ambiguity_type: AmbiguityType) -> int:
        """
        Get priority index for ambiguity type.

        Args:
            ambiguity_type: Type of ambiguity

        Returns:
            Priority index (lower = higher priority)
        """
        try:
            return cls.PRIORITY_ORDER.index(ambiguity_type)
        except ValueError:
            # Unknown type, lowest priority
            return len(cls.PRIORITY_ORDER)

    @classmethod
    def filter_auto_resolvable(
        cls,
        ambiguities: List[AmbiguityContext],
        threshold: float = 0.85
    ) -> List[AmbiguityContext]:
        """
        Filter out auto-resolvable ambiguities.

        Auto-resolvable ambiguities are resolved automatically without HITL.
        Currently applies to VALUE ambiguity with confidence > threshold.

        Args:
            ambiguities: List of ambiguities
            threshold: Confidence threshold for auto-resolve

        Returns:
            Filtered list (non-auto-resolvable only)
        """
        filtered = []

        for ambiguity in ambiguities:
            if ambiguity.is_auto_resolvable(threshold):
                logger.info(
                    f"[AMBIGUITY_ROUTER] Auto-resolving {ambiguity.ambiguity_type}"
                )
                # Auto-resolve will be handled by fallback
                continue

            filtered.append(ambiguity)

        return filtered


# =============================================================================
# AMBIGUITY FALLBACK - Default resolution strategies
# =============================================================================

class AmbiguityFallback:
    """
    Provides fallback resolution strategies when:
    1. Auto-resolvable (high confidence)
    2. Max clarification count reached
    3. User provides invalid response

    Strategies:
    - Value ambiguity: Use highest confidence value
    - Context ambiguity: Keep filters by default (safe choice)
    - Column ambiguity: Use first matched column
    - Intent ambiguity: Assume new_query
    - Prompt scope: Assume list all records
    """

    @staticmethod
    def auto_resolve_value_ambiguity(
        ctx: AmbiguityContext,
        threshold: float = 0.85
    ) -> Optional[str]:
        """
        Auto-resolve value ambiguity with high confidence.

        Args:
            ctx: AmbiguityContext with type=VALUE
            threshold: Confidence threshold (default 0.85)

        Returns:
            Resolved value or None if cannot auto-resolve

        Example:
            ctx = AmbiguityContext(
                type=VALUE,
                candidates=["İstanbul", "İstanbul Mağazası"],
                confidence_scores={"İstanbul": 0.95, "İstanbul Mağazası": 0.3}
            )
            resolved = auto_resolve_value_ambiguity(ctx)
            # Returns "İstanbul"
        """
        if ctx.ambiguity_type != AmbiguityType.VALUE:
            return None

        result = ctx.get_highest_confidence_candidate()
        if not result:
            return None

        candidate, confidence = result

        if confidence >= threshold:
            logger.info(
                f"[FALLBACK] Auto-resolved value: '{candidate}' "
                f"(confidence={confidence:.2f})"
            )
            return str(candidate)

        return None

    @staticmethod
    def default_context_resolution(
        ctx: AmbiguityContext,
        keep_filters: bool = True
    ) -> Dict[str, Any]:
        """
        Default resolution for context ambiguity.

        Default behavior: KEEP filters (conservative choice).
        This prevents accidental data explosion.

        Args:
            ctx: AmbiguityContext with type=CONTEXT
            keep_filters: Whether to keep filters (default True)

        Returns:
            Resolution dict with execution_mode

        Example:
            resolution = default_context_resolution(ctx)
            # Returns {"execution_mode": "delta", "clear_context": False}
        """
        if ctx.ambiguity_type != AmbiguityType.CONTEXT:
            return {}

        if keep_filters:
            logger.info("[FALLBACK] Keeping filters (default)")
            return {
                "execution_mode": "delta",
                "clear_context": False,
                "intent_type": "modify_filter"
            }
        else:
            logger.info("[FALLBACK] Clearing filters")
            return {
                "execution_mode": "full",
                "clear_context": True,
                "intent_type": "new_query"
            }

    @staticmethod
    def default_column_resolution(
        ctx: AmbiguityContext
    ) -> Optional[str]:
        """
        Default resolution for column ambiguity.

        Strategy: Use first matched column.

        Args:
            ctx: AmbiguityContext with type=COLUMN

        Returns:
            Resolved column name or None
        """
        if ctx.ambiguity_type != AmbiguityType.COLUMN:
            return None

        if ctx.candidates:
            column = ctx.candidates[0]
            logger.info(f"[FALLBACK] Using first column: '{column}'")
            return str(column)

        return None

    @staticmethod
    def default_intent_resolution(
        ctx: AmbiguityContext
    ) -> str:
        """
        Default resolution for intent ambiguity.

        Strategy: Assume new_query (safe default).

        Args:
            ctx: AmbiguityContext with type=INTENT

        Returns:
            Resolved intent type
        """
        if ctx.ambiguity_type != AmbiguityType.INTENT:
            return "new_query"

        logger.info("[FALLBACK] Assuming new_query intent")
        return "new_query"

    @staticmethod
    def default_prompt_scope_resolution(
        ctx: AmbiguityContext
    ) -> str:
        """
        Default resolution for prompt scope ambiguity.

        Strategy: Assume "list all records".

        Args:
            ctx: AmbiguityContext with type=PROMPT_SCOPE

        Returns:
            Resolved clarification
        """
        if ctx.ambiguity_type != AmbiguityType.PROMPT_SCOPE:
            return "list_all"

        logger.info("[FALLBACK] Assuming 'list all records'")
        return "list_all"

    @staticmethod
    def resolve_fallback(
        ctx: AmbiguityContext,
        reason: str = "max_clarification_reached"
    ) -> Dict[str, Any]:
        """
        Apply appropriate fallback resolution based on ambiguity type.

        Args:
            ctx: AmbiguityContext to resolve
            reason: Reason for fallback (for logging)

        Returns:
            Resolution dict with type-specific fields

        Example:
            resolution = resolve_fallback(context_ambiguity, reason="timeout")
            # Returns {"execution_mode": "delta", "clear_context": False, ...}
        """
        logger.warning(
            f"[FALLBACK] Applying fallback for {ctx.ambiguity_type} "
            f"(reason: {reason})"
        )

        fallback_strategies = {
            AmbiguityType.VALUE: lambda: {
                "resolved_value": AmbiguityFallback.auto_resolve_value_ambiguity(ctx)
            },
            AmbiguityType.CONTEXT: lambda: AmbiguityFallback.default_context_resolution(ctx),
            AmbiguityType.COLUMN: lambda: {
                "resolved_column": AmbiguityFallback.default_column_resolution(ctx)
            },
            AmbiguityType.INTENT: lambda: {
                "resolved_intent": AmbiguityFallback.default_intent_resolution(ctx)
            },
            AmbiguityType.PROMPT_SCOPE: lambda: {
                "resolved_scope": AmbiguityFallback.default_prompt_scope_resolution(ctx)
            }
        }

        strategy = fallback_strategies.get(ctx.ambiguity_type)
        if strategy:
            return strategy()

        # Unknown type, return empty
        return {}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def should_trigger_hitl(
    state: Dict[str, Any],
    ambiguity: Optional[AmbiguityContext],
    max_clarifications: int = 3
) -> bool:
    """
    Determine if HITL should be triggered for given ambiguity.

    Considers:
    1. Clarification count limit
    2. Auto-resolvable ambiguities
    3. Ambiguity existence

    Args:
        state: Current ReportState
        ambiguity: Detected ambiguity
        max_clarifications: Maximum clarification attempts

    Returns:
        True if should trigger HITL, False if should fallback or continue
    """
    if not ambiguity:
        return False

    # Check clarification count
    clarification_count = state.get("clarification_count", 0)
    if clarification_count >= max_clarifications:
        logger.warning(
            f"[HITL] Max clarification count ({max_clarifications}) reached, "
            "using fallback"
        )
        return False

    # Check auto-resolvable
    if ambiguity.auto_resolvable:
        logger.info(f"[HITL] Ambiguity auto-resolvable, skipping HITL")
        return False

    return True


def apply_auto_resolution(
    state: Dict[str, Any],
    ambiguity: AmbiguityContext
) -> Dict[str, Any]:
    """
    Apply auto-resolution for ambiguity and update state.

    Args:
        state: Current ReportState
        ambiguity: Ambiguity to auto-resolve

    Returns:
        Updated state dict

    Example:
        new_state = apply_auto_resolution(state, value_ambiguity)
        # Automatically resolves and updates state
    """
    resolution = AmbiguityFallback.resolve_fallback(
        ambiguity,
        reason="auto_resolve"
    )

    # Update state with resolution
    updates = {}

    if ambiguity.ambiguity_type == AmbiguityType.VALUE:
        updates["_selected_value"] = resolution.get("resolved_value")

    elif ambiguity.ambiguity_type == AmbiguityType.CONTEXT:
        updates["_execution_mode"] = resolution.get("execution_mode")
        if resolution.get("clear_context"):
            updates["active_query_context"] = None

    elif ambiguity.ambiguity_type == AmbiguityType.COLUMN:
        updates["_selected_column"] = resolution.get("resolved_column")

    elif ambiguity.ambiguity_type == AmbiguityType.INTENT:
        updates["_intent_type"] = resolution.get("resolved_intent")

    elif ambiguity.ambiguity_type == AmbiguityType.PROMPT_SCOPE:
        # Enhance user query with resolved scope
        pass

    logger.info(f"[AUTO_RESOLVE] Applied resolution: {updates}")

    return {**state, **updates}
