"""
Entity Validator - Smart Entity Extraction & Validation Pipeline

Bu modül entity extraction için akıllı bir decision layer sağlar.
Context analizi, strategy selection ve post-validation içerir.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


# =============================================================================
# CONTEXT ANALYZER
# =============================================================================

def analyze_context_for_entities(
    conversation_history: Optional[List],
    user_query: str
) -> Dict[str, Any]:
    """
    Analyze conversation context to determine entity availability.

    Args:
        conversation_history: Previous conversation entries
        user_query: Current user query

    Returns:
        {
            "has_context": bool,
            "context_entities": [...],
            "context_entity_column": "...",
            "context_source": "extracted_entities" | "results",
            "query_has_entities": bool,
            "query_has_reference": bool,  # "bunu", "bunları", "diğer" etc.
            "is_expansion_query": bool,  # NEW: "diğer şubeler", "tüm şubeler" etc.
            "expansion_type": str | None,  # NEW: "all", "all_others", "specific_expand"
            "recommended_strategy": "use_context" | "use_query" | "mixed" | "expand_context" | "needs_clarification"
        }
    """
    result = {
        "has_context": False,
        "context_entities": [],
        "context_entity_column": None,
        "context_source": None,
        "query_has_entities": False,
        "query_has_reference": False,
        "is_expansion_query": False,  # NEW
        "expansion_type": None,  # NEW
        "recommended_strategy": "needs_clarification"
    }

    # Check conversation history
    if not conversation_history or len(conversation_history) == 0:
        logger.info("[CONTEXT_ANALYZER] No conversation history")
        result["recommended_strategy"] = "use_query"
        return result

    last_conv = conversation_history[-1]

    # Try to extract entities from context
    # Priority 1: extracted_entities field (new format)
    extracted_ents = last_conv.get("extracted_entities", {})
    if extracted_ents and extracted_ents.get("entities"):
        result["has_context"] = True
        result["context_entities"] = extracted_ents.get("entities", [])
        result["context_entity_column"] = (
            extracted_ents.get("entity_column") or
            extracted_ents.get("entity_type")
        )
        result["context_source"] = "extracted_entities"
        logger.info(f"[CONTEXT_ANALYZER] Found entities from extracted_entities: "
                   f"{result['context_entities'][:3]}")

    # Priority 2: results field (old format - fallback)
    elif "results" in last_conv and last_conv["results"]:
        results = last_conv["results"]
        if results and len(results) > 0:
            first_key = list(results[0].keys())[0]
            result["has_context"] = True
            result["context_entities"] = [r.get(first_key) for r in results[:10] if r.get(first_key)]
            result["context_entity_column"] = first_key
            result["context_source"] = "results"
            logger.info(f"[CONTEXT_ANALYZER] Found entities from results: "
                       f"{result['context_entities'][:3]}")

    # Analyze user query for entities and references
    query_lower = user_query.lower()

    # ==================================================================
    # EXPANSION DETECTION (Kural Tabanlı - Token Tasarruflu!)
    # ==================================================================
    # "diğer şubeler", "tüm şubeler", "hepsi", "all" gibi ifadeler
    expansion_patterns = {
        "all": ["tüm", "hepsi", "bütün", "all", "tümü"],
        "all_others": ["diğer", "diğerleri", "geri kalan", "öteki", "kalan"],
        "specific_expand": ["başka", "ayrıca", "de", "da"]  # "X de", "Y da"
    }

    detected_expansion = None
    for exp_type, keywords in expansion_patterns.items():
        if any(kw in query_lower for kw in keywords):
            detected_expansion = exp_type
            result["is_expansion_query"] = True
            result["expansion_type"] = exp_type
            logger.info(f"[EXPANSION_DETECT] Detected: {exp_type} (keywords: {[kw for kw in keywords if kw in query_lower]})")
            break

    # Check for reference keywords
    reference_keywords = [
        "bunu", "bu", "onu", "bunları", "onları",
        "bu iki", "bu ikisi", "ikisi", "bu kategorileri"
    ]
    result["query_has_reference"] = any(kw in query_lower for kw in reference_keywords)

    # Check for explicit entities (basic heuristic)
    comparison_indicators = ["vs", " ile ", "karşı", "karşılaştır", "kıyasla"]
    has_comparison = any(ind in query_lower for ind in comparison_indicators)

    # Simple check: if query is long and has comparison, might have entities
    if has_comparison and len(user_query.split()) > 3:
        result["query_has_entities"] = True

    # ==================================================================
    # SMART STRATEGY SELECTION (Deterministik - Token Tasarruflu!)
    # ==================================================================
    if result["is_expansion_query"] and result["has_context"]:
        # EXPANSION QUERY: "diğer şubeler", "tüm şubeler"
        result["recommended_strategy"] = "expand_context"
        logger.info(f"[STRATEGY] EXPANSION detected → expand_context")

    elif result["has_context"] and result["query_has_reference"]:
        # Context exists and query references it
        if result["query_has_entities"]:
            result["recommended_strategy"] = "mixed"  # Context + query entities
        else:
            result["recommended_strategy"] = "use_context"  # Only context

    elif result["has_context"] and result["query_has_entities"]:
        # Context exists and query has new entities
        result["recommended_strategy"] = "mixed"

    elif result["has_context"] and not result["query_has_reference"]:
        # Context exists but query doesn't reference it (new query?)
        result["recommended_strategy"] = "use_query"

    elif not result["has_context"] and result["query_has_entities"]:
        # No context, query has entities
        result["recommended_strategy"] = "use_query"

    else:
        # Unclear - needs clarification
        result["recommended_strategy"] = "needs_clarification"
        logger.warning("[CONTEXT_ANALYZER] Unclear situation, needs clarification")

    logger.info(f"[CONTEXT_ANALYZER] Strategy: {result['recommended_strategy']}, "
               f"has_context={result['has_context']}, "
               f"query_has_reference={result['query_has_reference']}, "
               f"query_has_entities={result['query_has_entities']}")

    return result


# =============================================================================
# ENTITY EXTRACTION STRATEGIES
# =============================================================================

async def extract_entities_with_strategy(
    strategy: str,
    user_query: str,
    query_type: str,
    context_analysis: Dict[str, Any],
    llm: BaseChatModel
) -> Dict[str, Any]:
    """
    Extract entities based on strategy (TOKEN EFFICIENT!).

    Args:
        strategy: "use_context", "use_query", "mixed", "expand_context", "needs_clarification"
        user_query: User query
        query_type: Query type
        context_analysis: Context analysis result
        llm: Language model

    Returns:
        Entity extraction result
    """
    if strategy == "needs_clarification":
        logger.warning("[ENTITY_STRATEGY] Strategy is needs_clarification, skipping extraction")
        return {
            "entities": [],
            "entity_column": None,
            "confidence": 0.0,
            "needs_clarification": True,
            "reasoning": "Context belirsiz veya yetersiz"
        }

    elif strategy == "expand_context":
        # EXPANSION STRATEGY: "diğer şubeler", "tüm şubeler"
        # Token Efficient: NO LLM CALL! Just return SQL hints
        logger.info("[ENTITY_STRATEGY] 🚀 EXPANSION strategy (token efficient!)")

        expansion_type = context_analysis.get("expansion_type", "all_others")
        entity_column = context_analysis.get("context_entity_column")

        if expansion_type == "all":
            # "Tüm şubeler" → Remove filter, GROUP BY all
            logger.info("[EXPANSION] Type: ALL - Remove filter, show all entities")
            return {
                "entities": ["__ALL__"],  # Special marker
                "entity_column": entity_column,
                "entity_source": "expansion_all",
                "confidence": 0.95,  # Deterministic, high confidence
                "needs_clarification": False,
                "reasoning": "Tüm entity'ler istendi (filtre kaldırıldı)",
                # SQL HINTS (for SQL generation)
                "sql_hints": {
                    "remove_entity_filter": True,
                    "group_by_column": entity_column,
                    "expansion_mode": "all"
                }
            }

        elif expansion_type == "all_others":
            # "Diğer şubeler" → Context entity + ALL others
            logger.info("[EXPANSION] Type: ALL_OTHERS - Include context + all others")
            context_entities = context_analysis.get("context_entities", [])

            return {
                "entities": context_entities + ["__ALL_OTHERS__"],  # Context + marker
                "entity_column": entity_column,
                "entity_source": "expansion_all_others",
                "confidence": 0.90,  # Deterministic, high confidence
                "needs_clarification": False,
                "reasoning": f"Context entity ({context_entities[:3]}) + tüm diğer entity'ler",
                # SQL HINTS
                "sql_hints": {
                    "remove_entity_filter": True,  # Remove filter to get all
                    "group_by_column": entity_column,
                    "expansion_mode": "all_others",
                    "context_entities": context_entities  # For reference
                }
            }

        else:  # specific_expand
            # "X de", "Y da" → Need LLM to extract specific entities
            logger.info("[EXPANSION] Type: SPECIFIC - Need LLM extraction")
            # Fall back to mixed strategy
            strategy = "mixed"

    if strategy == "use_context":
        # Use only context entities
        logger.info("[ENTITY_STRATEGY] Using context entities only")
        entities = context_analysis["context_entities"][:5]  # Max 5 entities
        return {
            "entities": entities,
            "entity_column": context_analysis["context_entity_column"],
            "entity_source": "context",
            "confidence": 0.85,  # High confidence for context reuse
            "needs_clarification": len(entities) < 2,  # Need at least 2 for comparison
            "reasoning": "Context'ten entity'ler alındı"
        }

    elif strategy == "use_query":
        # Extract entities from query only
        logger.info("[ENTITY_STRATEGY] Extracting entities from query only")
        from .query_type_actions import extract_entities_from_context
        return await extract_entities_from_context(
            user_query=user_query,
            query_type=query_type,
            conversation_history=None,  # No context
            llm=llm
        )

    elif strategy == "mixed":
        # Combine context + query
        logger.info("[ENTITY_STRATEGY] Mixed strategy: context + query")
        from .query_type_actions import extract_entities_from_context

        # Extract from query with context
        result = await extract_entities_from_context(
            user_query=user_query,
            query_type=query_type,
            conversation_history=[{
                "extracted_entities": {
                    "entities": context_analysis["context_entities"],
                    "entity_column": context_analysis["context_entity_column"]
                }
            }],
            llm=llm
        )

        # Ensure we have context entities
        if len(result["entities"]) == 0:
            # Fallback to context
            result["entities"] = context_analysis["context_entities"][:5]
            result["entity_column"] = context_analysis["context_entity_column"]
            result["entity_source"] = "context_fallback"
            result["confidence"] = 0.75

        return result

    else:
        logger.error(f"[ENTITY_STRATEGY] Unknown strategy: {strategy}")
        return {
            "entities": [],
            "entity_column": None,
            "confidence": 0.0,
            "needs_clarification": True,
            "reasoning": f"Unknown strategy: {strategy}"
        }


# =============================================================================
# POST-VALIDATION
# =============================================================================

def post_validate_entities(
    extraction_result: Dict[str, Any],
    query_type: str,
    context_analysis: Dict[str, Any]
) -> Tuple[bool, Optional[str]]:
    """
    Validate extraction results after extraction (EXPANSION AWARE).

    Args:
        extraction_result: Result from extraction
        query_type: Query type
        context_analysis: Context analysis result

    Returns:
        (is_valid, error_reason)
    """
    entities = extraction_result.get("entities", [])
    confidence = extraction_result.get("confidence", 0.0)
    needs_clarification = extraction_result.get("needs_clarification", False)
    entity_source = extraction_result.get("entity_source", "")

    # EXPANSION QUERIES: Skip entity count check (they're valid by design)
    is_expansion = entity_source in ["expansion_all", "expansion_all_others"]
    if is_expansion:
        logger.info(f"[POST_VALIDATE] ✓ Expansion query detected, skipping count check")
        # Still check other rules but skip entity count
    else:
        # Rule 1: Comparison queries need 2+ entities (non-expansion)
        if query_type in ["comparison", "time_series_comparison"]:
            if len(entities) < 2:
                logger.warning(f"[POST_VALIDATE] Comparison query needs 2+ entities, got {len(entities)}")
                return False, "comparison_needs_2_entities"

    # Rule 2: Confidence threshold
    CONFIDENCE_THRESHOLD = 0.75
    if confidence < CONFIDENCE_THRESHOLD:
        logger.warning(f"[POST_VALIDATE] Low confidence: {confidence:.2f} < {CONFIDENCE_THRESHOLD}")
        return False, "low_confidence"

    # Rule 3: LLM says needs clarification
    if needs_clarification:
        logger.warning(f"[POST_VALIDATE] LLM flagged needs_clarification")
        return False, "llm_needs_clarification"

    # Rule 4: No entity column detected
    if not extraction_result.get("entity_column"):
        logger.warning(f"[POST_VALIDATE] No entity column detected")
        return False, "no_entity_column"

    # All checks passed
    logger.info(f"[POST_VALIDATE] ✓ Validation passed: {len(entities)} entities, "
               f"confidence={confidence:.2f}, source={entity_source}")
    return True, None


# =============================================================================
# MAIN PIPELINE
# =============================================================================

async def smart_entity_validation_pipeline(
    user_query: str,
    query_type: str,
    conversation_history: Optional[List],
    llm: BaseChatModel
) -> Dict[str, Any]:
    """
    Smart entity validation pipeline with decision layer.

    Pipeline:
    1. Analyze context
    2. Determine strategy
    3. Extract entities
    4. Post-validate
    5. Return result

    Args:
        user_query: User query
        query_type: Query type
        conversation_history: Conversation history
        llm: Language model

    Returns:
        {
            "entities": [...],
            "entity_column": "...",
            "confidence": 0.0-1.0,
            "needs_clarification": bool,
            "validation_passed": bool,
            "strategy_used": "...",
            "reasoning": "..."
        }
    """
    logger.info("=" * 80)
    logger.info("[ENTITY_VALIDATION_PIPELINE] Starting smart entity validation")
    logger.info(f"  Query: {user_query[:100]}")
    logger.info(f"  Query Type: {query_type}")
    logger.info(f"  Has History: {bool(conversation_history)}")

    # Step 1: Analyze context
    logger.info("[STEP 1] Analyzing context...")
    context_analysis = analyze_context_for_entities(conversation_history, user_query)

    # Step 2: Determine strategy
    strategy = context_analysis["recommended_strategy"]
    logger.info(f"[STEP 2] Selected strategy: {strategy}")

    # Step 3: Extract entities
    logger.info(f"[STEP 3] Extracting entities with strategy: {strategy}")
    extraction_result = await extract_entities_with_strategy(
        strategy=strategy,
        user_query=user_query,
        query_type=query_type,
        context_analysis=context_analysis,
        llm=llm
    )

    # Step 4: Post-validate
    logger.info(f"[STEP 4] Post-validating extraction result")
    is_valid, error_reason = post_validate_entities(
        extraction_result,
        query_type,
        context_analysis
    )

    # Step 5: Build final result
    result = {
        **extraction_result,
        "validation_passed": is_valid,
        "validation_error": error_reason,
        "strategy_used": strategy,
        "context_analysis": context_analysis
    }

    # Override needs_clarification if validation failed
    if not is_valid:
        result["needs_clarification"] = True
        logger.warning(f"[PIPELINE] Validation failed: {error_reason}, needs clarification")

    logger.info(f"[PIPELINE] Pipeline complete:")
    logger.info(f"  Entities: {result['entities'][:3]}")
    logger.info(f"  Confidence: {result['confidence']:.2f}")
    logger.info(f"  Needs Clarification: {result['needs_clarification']}")
    logger.info(f"  Strategy: {strategy}")
    logger.info("=" * 80)

    return result
