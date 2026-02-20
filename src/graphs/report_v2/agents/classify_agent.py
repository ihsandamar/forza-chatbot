"""
ClassifyAgent — Report V2

LangGraph native parallel fan-out after classify_intent:
  classify_intent
       ├─→ detect_references   (writes _reference_context)
       └─→ validate_entities   (writes _extracted_entities, _entity_validation_done)
            ↓
       detect_ambiguity  (fan-in, reads both)
            ↓
  route_after_ambiguity
       ├─→ hitl_clarification → process_clarification → classify_intent (loop)
       └─→ build_result → END
"""

import json
import logging
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from src.graphs.report.state import ActiveQueryContext, PendingQuestion
from src.graphs.report_v2.state import ClassifyResult

logger = logging.getLogger(__name__)


# =============================================================================
# HITL CONFIGURATION
# =============================================================================

def _load_hitl_config() -> Dict[str, Any]:
    """
    Load enhanced HITL configuration from config.yaml.

    Returns default values if config not found or parsing fails.
    """
    try:
        config_path = Path("config/config.yaml")
        if not config_path.exists():
            logger.warning("[HITL_CONFIG] config.yaml not found, using defaults")
            return _get_default_hitl_config()

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        report_config = config.get("report", {})
        hitl_config = report_config.get("hitl", {})

        defaults = _get_default_hitl_config()
        return {**defaults, **hitl_config}

    except Exception as e:
        logger.error(f"[HITL_CONFIG] Error loading config: {e}, using defaults")
        return _get_default_hitl_config()


def _get_default_hitl_config() -> Dict[str, Any]:
    """Get default HITL configuration."""
    return {
        "enable_enhanced_hitl": True,
        "max_clarifications": 3,
        "max_clarification_count": 3,
        "auto_resolve_threshold": 0.85,
        "enable_context_ambiguity": True,
        "enable_prompt_scope_ambiguity": True,
        "enable_intent_ambiguity": True,
        "enable_column_ambiguity": True,
        "enable_value_ambiguity": True,
    }


# Load config at module level
HITL_CONFIG = _load_hitl_config()
logger.info(f"[HITL_CONFIG] Loaded: enable_enhanced_hitl={HITL_CONFIG.get('enable_enhanced_hitl')}")


# =============================================================================
# METRICS TRACKING
# =============================================================================

HITL_METRICS = {
    "ambiguity_distribution": {},
    "auto_resolve_count": 0,
    "hitl_trigger_count": 0,
    "clarification_counts": [],
}


def _track_ambiguity_metric(ambiguity_type: str, event: str = "detected") -> None:
    """Track ambiguity metrics for monitoring."""
    try:
        monitoring_config = HITL_CONFIG.get("monitoring", {})
        track_distribution = monitoring_config.get("track_ambiguity_distribution", True)

        if not track_distribution:
            return

        key = f"{ambiguity_type}_{event}"
        HITL_METRICS["ambiguity_distribution"][key] = \
            HITL_METRICS["ambiguity_distribution"].get(key, 0) + 1

        if event == "auto_resolved":
            HITL_METRICS["auto_resolve_count"] += 1
        elif event == "detected":
            HITL_METRICS["hitl_trigger_count"] += 1

        total_events = sum(HITL_METRICS["ambiguity_distribution"].values())
        if total_events % 10 == 0:
            logger.info(f"[HITL_METRICS] Distribution: {HITL_METRICS['ambiguity_distribution']}")

    except Exception as e:
        logger.error(f"[HITL_METRICS] Error tracking metric: {e}")


def _calculate_auto_resolve_rate() -> float:
    """Calculate auto-resolution success rate."""
    total = HITL_METRICS["hitl_trigger_count"]
    auto_resolved = HITL_METRICS["auto_resolve_count"]
    if total == 0:
        return 0.0
    return auto_resolved / total


def get_hitl_metrics() -> Dict[str, Any]:
    """Get current HITL metrics for monitoring dashboard."""
    avg_clarification = 0.0
    if HITL_METRICS["clarification_counts"]:
        avg_clarification = sum(HITL_METRICS["clarification_counts"]) / len(HITL_METRICS["clarification_counts"])

    return {
        "ambiguity_distribution": HITL_METRICS["ambiguity_distribution"].copy(),
        "auto_resolve_rate": _calculate_auto_resolve_rate(),
        "total_hitl_triggers": HITL_METRICS["hitl_trigger_count"],
        "total_auto_resolved": HITL_METRICS["auto_resolve_count"],
        "avg_clarification_count": avg_clarification,
    }


# =============================================================================
# CLASSIFY STATE
# =============================================================================

class ClassifyState(TypedDict):
    # INPUT
    user_input: str
    messages: List[BaseMessage]
    conversation_history: List[Dict[str, Any]]
    active_context: Optional[ActiveQueryContext]
    user_clarification: Optional[str]
    clarification_count: int
    # INTERNAL
    _intent_type: Optional[str]
    _confidence: Optional[float]
    _query_type: Optional[str]
    _query_type_confidence: Optional[float]
    _needs_clarification: Optional[bool]
    _pending_question: Optional[PendingQuestion]
    _user_query: Optional[str]
    _ambiguity_context: Optional[Any]
    _modification_action: Optional[str]
    _clarification_type: Optional[str]     # detect_ambiguity_node writes this, hitl reads it
    # Parallel node outputs (different keys — no conflict)
    _reference_context: Optional[Dict[str, Any]]   # detect_references_node writes this
    _extracted_entities: Optional[Dict[str, Any]]  # validate_entities_node writes this
    _entity_validation_done: Optional[bool]        # validate_entities_node writes this
    # OUTPUT
    classify_result: Optional[ClassifyResult]


# =============================================================================
# HELPER: create_classify_input
# =============================================================================

def create_classify_input(orchestrator_state: Dict[str, Any]) -> ClassifyState:
    """
    Maps OrchestratorState → ClassifyState.

    Copies relevant fields and initialises internals to None/False.
    """
    return ClassifyState(
        user_input=orchestrator_state.get("user_input", ""),
        messages=orchestrator_state.get("messages", []),
        conversation_history=orchestrator_state.get("conversation_history", []),
        active_context=orchestrator_state.get("active_context"),
        user_clarification=orchestrator_state.get("user_clarification"),
        clarification_count=orchestrator_state.get("clarification_count", 0),
        # INTERNAL — all None/False at entry
        _intent_type=None,
        _confidence=None,
        _query_type=None,
        _query_type_confidence=None,
        _needs_clarification=None,
        _pending_question=None,
        _user_query=None,
        _ambiguity_context=None,
        _modification_action=None,
        _clarification_type=None,
        # Parallel outputs
        _reference_context=None,
        _extracted_entities=None,
        _entity_validation_done=False,
        # OUTPUT
        classify_result=None,
    )


# =============================================================================
# HELPER: get last user message from ClassifyState
# =============================================================================

def _get_last_user_message(state: ClassifyState) -> Optional[str]:
    """Extract the last HumanMessage from state.messages or fall back to user_input."""
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content
    return state.get("user_input") or None


# =============================================================================
# REFERENCE DETECTION HELPERS (LLM-driven)
# =============================================================================

async def _detect_references_llm(
    user_message: str,
    llm,
    conversation_history: Optional[list] = None
) -> Dict[str, Any]:
    """
    LLM-driven reference detection.

    CRITICAL: Uses LLM to understand natural language context, NOT pattern matching!

    Examples:
        "bu şubeler" → LLM detects reference to previous branches
        "onların satışı" → LLM understands "onların" refers to previous results
        "en çok ciro yapan şubeler" → LLM knows this is NEW query, not reference
        "bu ay satışlar" → LLM distinguishes time reference from previous results

    Args:
        user_message: User's query
        llm: Language model
        conversation_history: Previous queries (for context)

    Returns:
        Dict with:
            - has_reference: bool
            - reference_type: str ("previous_results", "time", "none")
            - confidence: float
            - needs_context: bool
    """
    context_info = "Yok"
    if conversation_history and len(conversation_history) > 0:
        last_query = conversation_history[-1].get("query", "")
        context_info = f"Önceki sorgu: {last_query}"

    prompt = f"""Kullanıcının sorgusu önceki sonuçlara referans veriyor mu?

Kullanıcı Sorusu: {user_message}
Context: {context_info}

ÖNEMLI:
- "bu şubeler", "onlar", "bunları" → önceki sonuçlara referans
- "ile karşılaştır", "ile kıyasla", "vs", "karşılaştır", "kıyasla" + önceki context var → önceki sorguya YENİ ENTITY EKLE (referans)
- "Peki X ile karşılaştır" → önceki sorgu + X ekle (referans)
- "X vs Y" (context yok) → YENİ sorgu, referans DEĞİL
- "bu ay", "bu yıl" → zaman referansı, önceki sonuç DEĞİL
- "en çok satan" → YENİ sorgu, referans DEĞİL

KRİTİK: Karşılaştırma ifadeleri ("ile karşılaştır", "vs", "kıyasla") ÖNCEKİ CONTEXT VARSA follow-up olarak algılanmalı!
- "Peki içecekler ile karşılaştır" (önceki sorgu: aylık dürümler) → REFERANS VAR (önceki query + içecekler ekle)
- "İstanbul vs Ankara" (context yok) → REFERANS YOK (yeni sorgu)

JSON döndür (sadece JSON):
{{
    "has_reference": true,
    "reference_type": "previous_results",
    "confidence": 0.9,
    "reasoning": "Kullanıcı 'ile karşılaştır' diyerek önceki sorguya yeni entity eklemek istiyor"
}}

reference_type seçenekleri:
- "previous_results": Önceki sorgu sonuçlarına referans
- "time": Zaman referansı (bu ay, bu yıl)
- "none": Referans yok"""

    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)

        has_reference = data.get("has_reference", False)
        reference_type = data.get("reference_type", "none")
        confidence = float(data.get("confidence", 0.5))
        reasoning = data.get("reasoning", "")

        # Only "previous_results" type counts as true reference
        if reference_type != "previous_results":
            has_reference = False

        logger.info(f"[REFERENCE_LLM] Message: '{user_message[:50]}...', "
                    f"has_reference={has_reference}, type={reference_type}, "
                    f"conf={confidence:.2f}, reasoning='{reasoning[:50]}...'")

        return {
            "has_reference": has_reference,
            "reference_type": reference_type,
            "confidence": confidence,
            "needs_context": has_reference,
            "reasoning": reasoning
        }

    except json.JSONDecodeError as e:
        logger.error(f"[REFERENCE_LLM] JSON parse error: {e}. Content: {content[:100]}")
        return {
            "has_reference": False,
            "reference_type": "none",
            "confidence": 0.0,
            "needs_context": False,
            "reasoning": "JSON parse error - fallback to no reference"
        }
    except Exception as e:
        logger.error(f"[REFERENCE_LLM] Error: {e}")
        return {
            "has_reference": False,
            "reference_type": "none",
            "confidence": 0.0,
            "needs_context": False,
            "reasoning": f"Error during LLM call: {str(e)}"
        }


async def _analyze_query_with_context(
    user_message: str,
    active_context: Optional[Dict],
    conversation_history: Optional[list],
    last_query_results: Optional[Dict],
    llm
) -> Dict[str, Any]:
    """
    LLM-driven context-aware query analysis.

    CRITICAL: ALL NLP is LLM-driven!
    - Reference detection (LLM)
    - Query type classification (LLM)
    - Ambiguity detection (LLM)

    Returns:
        {
            "query_type": str,
            "confidence": float,
            "is_followup": bool,
            "needs_clarification": bool,
            "reference_context": Dict
        }
    """
    # 1. LLM-driven reference detection
    ref_detection = await _detect_references_llm(
        user_message=user_message,
        llm=llm,
        conversation_history=conversation_history
    )
    is_followup = ref_detection["has_reference"]

    # 2. Build context for LLM
    context_parts = []
    previous_context = ""

    if is_followup and conversation_history:
        last_conv = conversation_history[-1]
        prev_query = last_conv.get("query", "")
        prev_type = last_conv.get("query_type", "")
        prev_results = last_conv.get("results", [])
        prev_filters = last_conv.get("filters", [])
        prev_grouping = last_conv.get("grouping", [])

        prev_entities = []
        if prev_results and len(prev_results) > 0:
            first_key = list(prev_results[0].keys())[0]
            prev_entities = [r.get(first_key) for r in prev_results[:5]]

        filter_info = ""
        if prev_filters:
            filter_info = f"\nÖnceki Filtreler: {prev_filters}"

        grouping_info = ""
        if prev_grouping:
            grouping_info = f"\nÖnceki Gruplama (GROUP BY): {prev_grouping}"

        previous_context = f"""
Önceki Sorgu: "{prev_query}"
Query Type: {prev_type}
Sonuçlar: {prev_entities}{filter_info}{grouping_info}
Kullanıcı bu sonuçlara referans veriyor.

⚠️ KRİTİK: KARŞILAŞTIRMA FOLLOW-UP için:
- Eğer kullanıcı "X ile karşılaştır", "vs", "kıyasla" diyorsa
- Ve önceki sorguda GRUPLAMA (GROUP BY) varsa
- YENİ sorgu da AYNI GRUPLAMA ile yapılmalı!
- Örnek: Önceki → "aylık dürümler" (GROUP BY YEAR, MONTH)
          Yeni → "içecekler ile karşılaştır"
          Sonuç → "aylık dürümler vs içecekler" (GROUP BY YEAR, MONTH KORUNMALI!)
"""
        context_parts.append(f"Önceki sorgu: {prev_type}")

    # 3. LLM prompt for query type classification
    prompt = f"""
    Görev: Kullanıcının sorgu intent'ini tek bir query_type ile sınıflandır.

    INPUT
    Soru: {user_message}
    Context: {' | '.join(context_parts) if context_parts else 'Yok'}
    Referans Durumu: {'Follow-up (önceki sonuçları kullanmalı)' if is_followup else 'Bağımsız'}

    {previous_context if is_followup else ''}

    TEMEL AYRIMLAR

    1) ZAMAN FİLTRESİ ≠ ZAMAN GRANULARITY
    - Zaman filtresi: "son 1 yıl", "2024'te", "geçen ay"
    - Zaman granularity: "aylık", "günlük", "haftalık", "ay ay", "gün gün", "aylara göre"

    Zaman filtresi tek başına time_series değildir.
    Granularity varsa zaman serisi vardır.

    QUERY TYPES (yalnızca biri seçilecek)

    1. single_value
    Tanım: Tek sayısal sonuç. Gruplama ve sıralama yok.
    İndikatörler: toplam, ortalama, kaç, ne kadar, miktar, maksimum, minimum
    Örnek:
    - "Toplam ciro nedir?"
    - "Kaç sipariş var?"
    Karar Kuralı:
    - Tek metrik
    - Grup yok
    - Top-N yok

    2. ranking
    Tanım: Top-N sıralama.
    İndikatörler: en çok, en az, top, ilk, son, N adet
    Örnek:
    - "En çok satan 10 ürün"
    Karar Kuralı:
    - Sıralama var
    - Genelde sayı belirtilmiş

    3. comparison
    Tanım: 2+ entity karşılaştırması, tek zaman noktası/dönem.
    Zaman filtresi olabilir.
    Granularity olmamalı.
    Örnek:
    - "İstanbul vs Ankara"
    - "Son 1 yılda A ve B karşılaştırması"
    Karar Kuralı:
    - 2+ entity
    - Granularity yok

    4. time_series
    Tanım: Tek entity'nin zaman içindeki değişimi.
    Granularity olabilir.
    Örnek:
    - "Son 6 aydaki satışlar"
    Karar Kuralı:
    - 1 entity
    - Zaman boyutu var

    5. time_series_comparison
    Tanım: 2+ entity + zaman granularity.
    Güçlü İndikatörler:
    - aylık bazda, ay ay, günlük, haftalık, aylara göre, günlere göre
    Örnek:
    - "X ve Y'nin aylık satışları"
    Karar Kuralı:
    - 2+ entity
    - Granularity açıkça belirtilmiş

    6. aggregation
    Tanım: Gruplama.
    İndikatör: "göre"
    Örnek:
    - "Kategorilere göre toplam ciro"
    Karar Kuralı:
    - Grup var
    - Top-N değil


    KRİTİK ÖNCELİK SIRASI (çakışma durumunda)
    1. ranking
    2. time_series_comparison
    3. time_series
    4. comparison
    5. aggregation
    6. single_value


    BELİRSİZLİK
    Eğer intent net değilse:
    - confidence < 0.65
    - needs_clarification = true

    ÇIKTI
    Sadece JSON döndür:

    {{
        "query_type": "comparison",
        "confidence": 0.87,
        "needs_clarification": false,
        "reasoning": "2 entity var, zaman filtresi var ancak granularity yok."
    }}
    """

    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)

        query_type = data.get("query_type", "aggregation")
        confidence = float(data.get("confidence", 0.5))
        needs_clarification = data.get("needs_clarification", False)
        reasoning = data.get("reasoning", "")

        # Validate query_type
        valid_types = ["single_value", "ranking", "comparison", "time_series",
                       "time_series_comparison", "aggregation", "distribution", "trend"]
        if query_type not in valid_types:
            logger.warning(f"[QUERY_ANALYSIS] Invalid query_type returned by LLM: '{query_type}'")
            logger.info(f"[QUERY_ANALYSIS] Asking LLM to map invalid query_type to valid type...")

            try:
                correction_prompt = f"""LLM yanlış query_type döndürdü: "{query_type}"

Geçerli query_type'lar SADECE şunlar:
- single_value
- ranking
- comparison
- time_series
- time_series_comparison
- aggregation
- distribution
- trend

Orijinal kullanıcı sorusu: "{user_message}"

"{query_type}" açıklamasını yukarıdaki geçerli query_type'lardan birine map et.

Sadece JSON döndür:
{{
    "corrected_query_type": "comparison",
    "reasoning": "Kullanıcı iki kategori karşılaştırıyor, zaman granularity yok"
}}"""

                correction_response = await llm.ainvoke(correction_prompt)
                correction_content = correction_response.content.strip()

                if "```json" in correction_content:
                    correction_content = correction_content.split("```json")[1].split("```")[0].strip()
                elif "```" in correction_content:
                    correction_content = correction_content.split("```")[1].split("```")[0].strip()

                correction_data = json.loads(correction_content)
                corrected_type = correction_data.get("corrected_query_type", "aggregation")

                if corrected_type in valid_types:
                    logger.info(f"[QUERY_ANALYSIS] LLM corrected '{query_type}' → '{corrected_type}'")
                    query_type = corrected_type
                    if confidence < 0.7:
                        confidence = 0.75
                        logger.info(f"[QUERY_ANALYSIS] Boosted confidence to {confidence} after successful LLM correction")
                else:
                    logger.error(f"[QUERY_ANALYSIS] LLM correction failed, using fallback")
                    query_type = "aggregation"
                    confidence = 0.3

            except Exception as e:
                logger.error(f"[QUERY_ANALYSIS] LLM correction error: {e}, using fallback")
                query_type = "aggregation"
                confidence = 0.3

        logger.info(f"[QUERY_ANALYSIS] Final query_type after validation: '{query_type}' (confidence: {confidence:.2f})")

        # Low confidence → clarification needed
        if confidence < 0.65:
            needs_clarification = True
            logger.warning(f"[QUERY_ANALYSIS] Low confidence ({confidence:.2f}), needs clarification")

        # Build reference context
        reference_context = {
            "is_followup": is_followup,
            "has_reference": ref_detection["has_reference"],
            "reference_type": ref_detection["reference_type"],
            "previous_entities": [],
            "entity_type": None
        }

        if is_followup and last_query_results:
            reference_context["previous_entities"] = last_query_results.get("entities", [])
            reference_context["entity_type"] = last_query_results.get("entity_type")

        logger.info(f"[QUERY_ANALYSIS] type={query_type}, conf={confidence:.2f}, "
                    f"followup={is_followup}, clarify={needs_clarification}, reasoning='{reasoning[:50]}...'")

        return {
            "query_type": query_type,
            "confidence": confidence,
            "is_followup": is_followup,
            "needs_clarification": needs_clarification,
            "reference_context": reference_context,
            "reasoning": reasoning
        }

    except json.JSONDecodeError as e:
        logger.error(f"[QUERY_ANALYSIS] JSON parse error: {e}. Content: {content[:100]}")
        return {
            "query_type": "aggregation",
            "confidence": 0.3,
            "is_followup": is_followup,
            "needs_clarification": True,
            "reference_context": {},
            "reasoning": "JSON parse error"
        }
    except Exception as e:
        logger.error(f"[QUERY_ANALYSIS] Error: {e}")
        return {
            "query_type": "aggregation",
            "confidence": 0.3,
            "is_followup": is_followup,
            "needs_clarification": True,
            "reference_context": {},
            "reasoning": f"Error: {str(e)}"
        }


# =============================================================================
# NODE 1: classify_intent_node
# =============================================================================

def _make_classify_intent_node(llm=None):
    """
    Returns an async node that classifies intent and sets:
    _intent_type, _confidence, _query_type, _query_type_confidence, _user_query.

    Migrated from create_intent_classifier_node() and
    create_conversation_aware_intent_node() in nodes.py.
    The llm parameter controls LLM vs rule-based path.
    """
    from src.graphs.report.intent import IntentClassifier, IntentType, SimpleIntentClassifier
    from src.graphs.report.tools import create_clarification_request
    from src.graphs.report.ambiguity_detectors import create_intent_detector
    from src.graphs.report.hitl_question_builder import HITLQuestionBuilder
    from src.graphs.report.ambiguity_router import should_trigger_hitl, apply_auto_resolution

    llm_classifier = IntentClassifier(llm) if llm else None
    simple_classifier = SimpleIntentClassifier()

    enable_fast_path = True

    async def classify_intent_node(state: ClassifyState) -> Dict[str, Any]:
        """
        Classify user intent.

        OPTIMIZATION: Fast-path pattern matching before LLM.
        Context varken HER ZAMAN LLM classifier kullanır.
        Context yokken önce fast-path, sonra simple classifier, en son LLM.
        """
        user_message = _get_last_user_message(state)
        if not user_message:
            return {"_intent_type": "new_query", "_confidence": 0.5, "_user_query": ""}

        logger.info(f"[CLASSIFY] Classifying intent: {user_message[:50]}...")

        user_lower = user_message.lower()
        active_context = state.get("active_context")
        has_context = active_context is not None

        # =====================================================================
        # FAST-PATH PATTERN MATCHING (only when no LLM or no context)
        # =====================================================================
        if enable_fast_path and not has_context:
            rollback_keywords = ["geri al", "iptal", "undo", "vazgeç", "önceki"]
            if any(kw in user_lower for kw in rollback_keywords):
                logger.info("[CLASSIFY] Fast path: ROLLBACK")
                return {
                    "_user_query": user_message,
                    "_intent_type": "rollback",
                    "_confidence": 1.0,
                }

            viz_keywords = ["grafik yap", "chart", "bar chart", "pasta grafik", "çubuk grafik",
                            "grafik çiz", "grafiğe dönüştür"]
            if any(kw in user_lower for kw in viz_keywords):
                logger.info("[CLASSIFY] Fast path: VISUALIZE")
                return {
                    "_user_query": user_message,
                    "_intent_type": "visualize",
                    "_confidence": 0.95,
                }

            simple_query_keywords = ["göster", "listele", "rapor", "getir", "bul", "say"]
            if any(kw in user_lower for kw in simple_query_keywords):
                if len(user_message.split()) <= 8:
                    logger.info("[CLASSIFY] Fast path: Simple NEW_QUERY")
                    return {
                        "_user_query": user_message,
                        "_intent_type": "new_query",
                        "_confidence": 0.85,
                        "_query_type": None,
                        "_query_type_confidence": 0.0,
                        "_needs_clarification": False,
                    }

            logger.debug("[CLASSIFY] No fast-path match, proceeding to classifier")

        # =====================================================================
        # STANDARD CLASSIFICATION PATH
        # =====================================================================

        if has_context and llm_classifier:
            logger.info("[CLASSIFY] Context exists, using LLM classifier")
            messages = state.get("messages", [])
            try:
                classification = await llm_classifier.classify(
                    user_message, messages, active_context
                )
                logger.info(f"[CLASSIFY] LLM classification: {classification.intent_type.value} "
                            f"(confidence: {classification.confidence})")
            except Exception as e:
                logger.error(f"[CLASSIFY] LLM classifier error: {e}, falling back to simple")
                classification = simple_classifier.classify(user_message, has_context)
        elif llm_classifier:
            # No context: try simple first, LLM if low confidence
            simple_result = simple_classifier.classify(user_message, has_context)
            if simple_result.confidence < 0.6:
                logger.info("[CLASSIFY] Low confidence, using LLM classifier")
                messages = state.get("messages", [])
                try:
                    classification = await llm_classifier.classify(
                        user_message, messages, active_context
                    )
                except Exception as e:
                    logger.error(f"[CLASSIFY] LLM classifier error: {e}")
                    classification = simple_result
            else:
                classification = simple_result
                logger.info(f"[CLASSIFY] Simple classifier sufficient: {classification.intent_type}")
        else:
            # No LLM at all — use simple classifier
            classification = simple_classifier.classify(user_message, has_context)
            logger.info(f"[CLASSIFY] (no-LLM) Simple classifier: {classification.intent_type}")

        # =====================================================================
        # ENHANCED HITL — AMBIGUITY DETECTION (v2.0)
        # =====================================================================
        enable_enhanced_hitl = HITL_CONFIG.get("enable_enhanced_hitl", True)

        if enable_enhanced_hitl:
            # Build temporary state-like dict for ambiguity detectors
            temp_state = {
                **{k: v for k, v in state.items()},
                "user_query": user_message,
                "_intent_type": classification.intent_type.value,
                "_confidence": classification.confidence,
                "_extracted_entities": classification.extracted_entities,
                # Map ClassifyState field names to ReportState equivalents
                "active_query_context": active_context,
                "conversation_history": state.get("conversation_history", []),
                "clarification_count": state.get("clarification_count", 0),
            }

            intent_detector = create_intent_detector()
            try:
                ambiguity = await intent_detector.detect_ambiguity(temp_state, stage="intent")
            except Exception as e:
                logger.error(f"[CLASSIFY] Ambiguity detection error: {e}")
                ambiguity = None

            max_clarifications = HITL_CONFIG.get("max_clarification_count", 3)

            if ambiguity and should_trigger_hitl(temp_state, ambiguity, max_clarifications):
                logger.warning(
                    f"[CLASSIFY] AMBIGUITY DETECTED: {ambiguity.ambiguity_type} — TRIGGERING HITL"
                )
                _track_ambiguity_metric(ambiguity.ambiguity_type, "detected")

                question_builder = HITLQuestionBuilder()
                question_template = question_builder.build_question(ambiguity)
                pending_question = question_template.to_pending_question()

                new_clarification_count = state.get("clarification_count", 0) + 1

                logger.info(f"[CLASSIFY] HITL question prepared: {pending_question['question'][:100]}...")

                return {
                    "_pending_question": pending_question,
                    "_ambiguity_context": ambiguity,
                    "clarification_count": new_clarification_count,
                    "_user_query": user_message,
                    "_intent_type": classification.intent_type.value,
                    "_confidence": classification.confidence,
                    "_needs_clarification": True,
                }

            if ambiguity and ambiguity.auto_resolvable:
                logger.info(f"[CLASSIFY] Auto-resolving {ambiguity.ambiguity_type}")
                try:
                    temp_state = apply_auto_resolution(temp_state, ambiguity)
                except Exception as e:
                    logger.error(f"[CLASSIFY] Auto-resolution error: {e}")
                _track_ambiguity_metric(ambiguity.ambiguity_type, "auto_resolved")

        # Legacy clarification (no enhanced ambiguity detected)
        if classification.requires_clarification and (not enable_enhanced_hitl):
            logger.info("[CLASSIFY] Legacy clarification required")
            if classification.clarification_question:
                question = classification.clarification_question
                options = classification.clarification_options or ["Evet", "Hayır"]
            else:
                question = "Ne yapmak istediğinizi tam anlayamadım."
                options = ["Yeni rapor oluştur", "Mevcut raporu değiştir"]

            pending_question: PendingQuestion = {
                "question": question,
                "options": options,
                "context": f"Tespit edilen niyet: {classification.intent_type.value}"
            }

            return {
                "_pending_question": pending_question,
                "_needs_clarification": True,
                "_user_query": user_message,
                "_intent_type": classification.intent_type.value,
                "_confidence": classification.confidence,
            }

        # =====================================================================
        # PHASE 2: CONTEXT-AWARE QUERY ANALYSIS (LLM-DRIVEN)
        # Note: The actual query analysis (reference detection + query type) is
        # now delegated to detect_references_node and the query_type part is
        # set here as a pass-through so detect_ambiguity_node can combine both.
        # =====================================================================
        # Note: _query_type and _query_type_confidence will be populated from
        # detect_references_node output combined in detect_ambiguity_node.
        # Here we just store the core intent classification result.

        return {
            "_user_query": user_message,
            "_intent_type": classification.intent_type.value,
            "_confidence": classification.confidence,
        }

    return classify_intent_node


# =============================================================================
# NODE 2: detect_references_node  (parallel — writes ONLY _reference_context)
# =============================================================================

def _make_detect_references_node(llm=None):
    """
    Returns async node that detects references and populates _reference_context.

    This was previously an internal helper called inside classify_intent.
    Now it runs IN PARALLEL with validate_entities_node.
    Writes ONLY to _reference_context.
    """

    async def detect_references_node(state: ClassifyState) -> Dict[str, Any]:
        """
        Detect query references and classify query type.
        Writes ONLY to _reference_context.
        """
        user_message = _get_last_user_message(state)
        if not user_message:
            return {"_reference_context": {}}

        conversation_history = state.get("conversation_history", [])
        active_context = state.get("active_context")

        if llm is None:
            # No LLM: return minimal reference context with no follow-up
            logger.info("[DETECT_REFS] No LLM available, skipping reference detection")
            reference_context = {
                "is_followup": False,
                "has_reference": False,
                "reference_type": "none",
                "previous_entities": [],
                "entity_type": None,
                "query_type": None,
                "query_type_confidence": 0.0,
                "needs_clarification": False,
            }
            return {"_reference_context": reference_context}

        logger.info(f"[DETECT_REFS] Running context-aware query analysis for: {user_message[:50]}...")

        # We have no last_query_results field on ClassifyState directly;
        # we derive it from conversation_history if available.
        last_query_results = None
        if conversation_history:
            last_conv = conversation_history[-1]
            extracted = last_conv.get("extracted_entities", {})
            results = last_conv.get("results", [])
            if results:
                first_key = list(results[0].keys())[0] if results[0] else None
                if first_key:
                    last_query_results = {
                        "entities": [r.get(first_key) for r in results],
                        "entity_type": first_key,
                    }
            elif extracted.get("entities"):
                last_query_results = {
                    "entities": extracted.get("entities", []),
                    "entity_type": extracted.get("entity_type"),
                }

        try:
            query_analysis = await _analyze_query_with_context(
                user_message=user_message,
                active_context=active_context,
                conversation_history=conversation_history,
                last_query_results=last_query_results,
                llm=llm
            )
        except Exception as e:
            logger.error(f"[DETECT_REFS] Query analysis failed: {e}", exc_info=True)
            query_analysis = {
                "query_type": None,
                "confidence": 0.0,
                "is_followup": False,
                "needs_clarification": False,
                "reference_context": {}
            }

        # Merge query_analysis into reference_context — this node writes _reference_context
        ref_ctx = query_analysis.get("reference_context", {})
        reference_context = {
            **ref_ctx,
            "query_type": query_analysis.get("query_type"),
            "query_type_confidence": query_analysis.get("confidence", 0.0),
            "needs_clarification": query_analysis.get("needs_clarification", False),
            "is_followup": query_analysis.get("is_followup", False),
        }

        logger.info(f"[DETECT_REFS] reference_context built: "
                    f"type={reference_context.get('query_type')}, "
                    f"conf={reference_context.get('query_type_confidence', 0):.2f}, "
                    f"followup={reference_context.get('is_followup', False)}")

        return {"_reference_context": reference_context}

    return detect_references_node


# =============================================================================
# NODE 3: validate_entities_node  (parallel — writes _extracted_entities, _entity_validation_done)
# =============================================================================

def _make_validate_entities_node(llm=None):
    """
    Returns async node for entity validation.
    Writes ONLY to _extracted_entities and _entity_validation_done.

    Migrated from create_validate_entities_node() in nodes.py.
    """

    async def validate_entities_node(state: ClassifyState) -> Dict[str, Any]:
        """
        Validate extracted entities and time period for queries.

        Checks:
        - Comparison/time_series_comparison needs minimum 2 entities
        - Time_series/time_series_comparison needs time period
        - If entities or period missing, flag for clarification

        Returns:
            State update with _extracted_entities and _entity_validation_done
        """
        # We won't know query_type until detect_ambiguity runs, but the
        # reference_context is not yet available here (parallel node).
        # Use the fast-path stored query type if any (from classify_intent fast-path),
        # otherwise skip heavy validation — detect_ambiguity will decide.
        query_type = state.get("_query_type")

        if query_type not in ["comparison", "time_series_comparison", "time_series"]:
            logger.info(f"[ENTITY_VALIDATE] Query type '{query_type}' doesn't require validation")
            return {
                "_extracted_entities": {},
                "_entity_validation_done": True,
            }

        user_message = _get_last_user_message(state)
        if not user_message:
            return {"_extracted_entities": {}, "_entity_validation_done": True}

        conversation_history = state.get("conversation_history", [])
        needs_clarification = False
        clarification_type = None

        # =================================================================
        # ENTITY VALIDATION (for comparison queries)
        # =================================================================
        entity_result = {}
        if query_type in ["comparison", "time_series_comparison"]:
            if llm:
                from src.graphs.report.entity_validator import smart_entity_validation_pipeline

                logger.info(f"[ENTITY_VALIDATE] Starting SMART entity validation pipeline for {query_type}")

                try:
                    entity_result = await smart_entity_validation_pipeline(
                        user_query=user_message,
                        query_type=query_type,
                        conversation_history=conversation_history,
                        llm=llm
                    )
                except Exception as e:
                    logger.error(f"[ENTITY_VALIDATE] Pipeline error: {e}")
                    entity_result = {}

                entities = entity_result.get("entities", [])
                entity_confidence = entity_result.get("confidence", 0.0)
                validation_passed = entity_result.get("validation_passed", False)
                strategy_used = entity_result.get("strategy_used", "unknown")

                logger.info(f"[ENTITY_VALIDATE] Pipeline result:")
                logger.info(f"  - Entities: {entities}")
                logger.info(f"  - Confidence: {entity_confidence:.2f}")
                logger.info(f"  - Strategy: {strategy_used}")
                logger.info(f"  - Validation: {'PASSED' if validation_passed else 'FAILED'}")

                if validation_passed:
                    needs_clarification = False
                    logger.info("[ENTITY_VALIDATE] Smart validation PASSED")
                else:
                    needs_clarification = True
                    clarification_type = "entity"
                    validation_error = entity_result.get("validation_error", "unknown")
                    logger.warning(f"[ENTITY_VALIDATE] Smart validation FAILED: {validation_error}")
            else:
                logger.info("[ENTITY_VALIDATE] No LLM — skipping entity validation")
                entity_result = {}

        elif query_type == "ranking":
            logger.info("[ENTITY_VALIDATE] Ranking query - entities will be extracted from results")

        # =================================================================
        # TIME PERIOD VALIDATION (for time_series queries)
        # =================================================================
        period_result = {}
        if query_type in ["time_series", "time_series_comparison"]:
            # Check user query for time indicators (no parsed_intent in ClassifyState)
            time_indicators = ["son", "geçen", "bu", "şu", "bu yıl", "geçen ay",
                               "son 6 ay", "son hafta"]
            if any(indicator in user_message.lower() for indicator in time_indicators):
                period = "inferred_from_query"
                period_source = "user_query"
            else:
                period = None
                period_source = None

            logger.info(f"[PERIOD_VALIDATE] Period: {period}, source: {period_source}")

            if not period:
                logger.warning("[PERIOD_VALIDATE] Time series query but no period found!")
                needs_clarification = True
                clarification_type = "period"

            period_result = {
                "period": period,
                "period_source": period_source,
                "has_period": bool(period)
            }

        # Build combined entity result for this node
        combined_entities = {
            **entity_result,
            **period_result,
            "_clarification_type": clarification_type,
            "_needs_clarification_from_entities": needs_clarification,
        }

        return {
            "_extracted_entities": combined_entities,
            "_entity_validation_done": True,
        }

    return validate_entities_node


# =============================================================================
# NODE 4: detect_ambiguity_node  (fan-in — reads _reference_context AND _extracted_entities)
# =============================================================================

def _make_detect_ambiguity_node(llm=None):
    """
    Fan-in node: reads both parallel outputs and determines if clarification needed.
    Sets _needs_clarification, _pending_question, _ambiguity_context, _query_type, _query_type_confidence.
    """

    async def detect_ambiguity_node(state: ClassifyState) -> Dict[str, Any]:
        """
        Fan-in: read _reference_context AND _extracted_entities (populated by parallel predecessors).
        Determine if we need HITL clarification.
        """
        reference_context = state.get("_reference_context") or {}
        extracted_entities = state.get("_extracted_entities") or {}
        entity_validation_done = state.get("_entity_validation_done", False)
        current_needs_clarification = state.get("_needs_clarification", False)

        # Extract query_type and confidence from reference_context
        query_type = reference_context.get("query_type")
        query_type_confidence = reference_context.get("query_type_confidence", 0.0)
        ref_needs_clarification = reference_context.get("needs_clarification", False)

        # Entity validation flag
        entity_needs_clarification = extracted_entities.get("_needs_clarification_from_entities", False)
        clarification_type = extracted_entities.get("_clarification_type")

        # Aggregate clarification decision
        needs_clarification = (
            current_needs_clarification
            or ref_needs_clarification
            or entity_needs_clarification
        )

        logger.info(f"[DETECT_AMBIGUITY] query_type={query_type}, conf={query_type_confidence:.2f}, "
                    f"needs_clarification={needs_clarification}, "
                    f"ref_needs={ref_needs_clarification}, entity_needs={entity_needs_clarification}")

        # Build pending question if clarification is needed but we don't have one yet
        pending_question = state.get("_pending_question")

        if needs_clarification and not pending_question:
            user_message = _get_last_user_message(state) or ""

            if entity_validation_done and clarification_type == "period":
                pending_question = {
                    "question": (
                        f'Sorgunuz: "{user_message}"\n\n'
                        "Hangi zaman aralığını analiz etmek istiyorsunuz?\n\n"
                        "Öneriler:\n"
                        "- Son 7 gün\n- Son 1 ay\n- Son 3 ay\n"
                        "- Son 6 ay\n- Son 1 yıl\n- Bu ay\n- Bu yıl\n\n"
                        "Lütfen zaman aralığını girin (örn: 'son 6 ay', 'bu yıl'):"
                    ),
                    "options": ["Son 7 gün", "Son 1 ay", "Son 3 ay",
                                "Son 6 ay", "Son 1 yıl", "Bu ay", "Bu yıl"],
                    "context": f"period_clarification|{query_type}"
                }

            elif entity_validation_done and clarification_type == "entity":
                entities = extracted_entities.get("entities", [])
                entity_column = extracted_entities.get("entity_column", "Entity")
                pending_question = {
                    "question": (
                        f'Sorgunuz: "{user_message}"\n\n'
                        f"Hangi {entity_column}'leri karşılaştırmak istiyorsunuz?\n\n"
                        + (f"Tespit edilen: {', '.join(entities)}\n\n" if entities else "")
                        + f"Lütfen karşılaştırmak istediğiniz en az 2 {entity_column} girin (virgülle ayırın):"
                    ),
                    "options": entities[:5] if entities else [],
                    "context": f"entity_clarification|{entity_column}"
                }

            else:
                # Query type clarification
                options_map = {
                    "ranking": "Sıralama (Top-N)",
                    "comparison": "Karşılaştırma (A vs B)",
                    "time_series": "Zaman Serisi",
                    "aggregation": "Gruplama/Toplam",
                    "distribution": "Dağılım",
                }
                context_info = ""
                is_followup = reference_context.get("is_followup", False)
                if is_followup:
                    prev_entities = reference_context.get("previous_entities", [])
                    if prev_entities:
                        context_info = f"\n\nÖnceki sonuçlar: {', '.join(str(e) for e in prev_entities[:3])}"

                options_text = "\n".join(f"- **{k}**: {v}" for k, v in options_map.items())
                pending_question = {
                    "question": (
                        f'Sorgunuz: "{user_message}"\n\n'
                        f"Sorgu türü belirsiz (güven: {query_type_confidence:.0%}). "
                        f"Hangi analiz türünü istiyorsunuz?{context_info}\n\n"
                        f"Seçenekler:\n{options_text}"
                    ),
                    "options": list(options_map.keys()),
                    "context": f"query_type_clarification|{query_type}"
                }

        result: Dict[str, Any] = {
            "_needs_clarification": needs_clarification,
            "_query_type": query_type,
            "_query_type_confidence": query_type_confidence,
        }

        if pending_question:
            result["_pending_question"] = pending_question

        if clarification_type:
            result["_clarification_type"] = clarification_type

        return result

    return detect_ambiguity_node


# =============================================================================
# NODE 5: hitl_clarification_node
# =============================================================================

async def hitl_clarification_node(state: ClassifyState) -> Dict[str, Any]:
    """
    Ask user for clarification using LangGraph interrupt().

    Migrated from ask_user_for_clarification_node() in nodes.py.
    Uses interrupt() from langgraph.types.
    """
    from langgraph.types import interrupt

    user_message = _get_last_user_message(state) or ""
    query_type = state.get("_query_type", "unknown")
    query_type_confidence = state.get("_query_type_confidence", 0.0)
    reference_context = state.get("_reference_context") or {}
    pending_question = state.get("_pending_question")
    extracted_entities = state.get("_extracted_entities") or {}

    logger.info(f"[HITL] Query type ambiguous: '{user_message[:50]}...', "
                f"type={query_type}, confidence={query_type_confidence:.2f}")

    # Determine clarification type from context
    clarification_type = state.get("_clarification_type") or \
        extracted_entities.get("_clarification_type")
    entity_validation_done = state.get("_entity_validation_done", False)

    # =================================================================
    # PERIOD CLARIFICATION
    # =================================================================
    if entity_validation_done and clarification_type == "period":
        message = (
            f'Sorgunuz: "{user_message}"\n\n'
            "Hangi zaman aralığını analiz etmek istiyorsunuz?\n\n"
            "Öneriler:\n"
            "- Son 7 gün\n- Son 1 ay\n- Son 3 ay\n"
            "- Son 6 ay\n- Son 1 yıl\n- Bu ay\n- Bu yıl\n\n"
            "Lütfen zaman aralığını girin (örn: 'son 6 ay', 'bu yıl'):"
        )

        user_input = interrupt({
            "message": message,
            "type": "period_clarification",
            "query_type": query_type
        })

        logger.info(f"[HITL] User clarified period: {user_input}")

        period_mapping = {
            "son 7 gün": "7 DAY",
            "son 1 ay": "1 MONTH",
            "son 3 ay": "3 MONTH",
            "son 6 ay": "6 MONTH",
            "son 1 yıl": "1 YEAR",
            "bu ay": "CURRENT_MONTH",
            "bu yıl": "CURRENT_YEAR",
        }

        period_value = None
        user_lower = user_input.lower().strip()
        for key, value in period_mapping.items():
            if key in user_lower:
                period_value = value
                break

        if not period_value:
            period_value = user_input

        updated_entities = {
            **(extracted_entities or {}),
            "period": period_value,
            "period_source": "user_clarification",
            "has_period": True,
            "_needs_clarification_from_entities": False,
        }
        return {
            "_extracted_entities": updated_entities,
            "_needs_clarification": False,
            "_clarification_type": None,
            "user_clarification": user_input,
        }

    # =================================================================
    # ENTITY CLARIFICATION
    # =================================================================
    if entity_validation_done and clarification_type == "entity" and \
            (extracted_entities or {}).get("needs_clarification"):

        entities = (extracted_entities or {}).get("entities", [])
        entity_column = (extracted_entities or {}).get("entity_column", "Entity")

        message = (
            f'Sorgunuz: "{user_message}"\n\n'
            f"Hangi {entity_column}'leri karşılaştırmak istiyorsunuz?\n\n"
            + (f"Tespit edilen: {', '.join(entities)}\n\n" if entities else "")
            + f"Lütfen karşılaştırmak istediğiniz en az 2 {entity_column} girin (virgülle ayırın):"
        )

        user_input = interrupt({
            "message": message,
            "type": "entity_clarification",
            "current_entities": entities,
            "entity_column": entity_column
        })

        clarified_entities = [e.strip() for e in user_input.split(",")]
        logger.info(f"[HITL] User clarified entities: {clarified_entities}")

        updated_entities = {
            **(extracted_entities or {}),
            "entities": clarified_entities,
            "entity_column": entity_column,
            "confidence": 1.0,
            "needs_clarification": False,
            "entity_source": "user_clarification",
            "_needs_clarification_from_entities": False,
        }
        return {
            "_extracted_entities": updated_entities,
            "_needs_clarification": False,
            "user_clarification": user_input,
        }

    # =================================================================
    # QUERY TYPE CLARIFICATION (generic)
    # =================================================================
    options = {
        "ranking": "Sıralama (Top-N)",
        "comparison": "Karşılaştırma (A vs B)",
        "time_series": "Zaman Serisi",
        "aggregation": "Gruplama/Toplam",
        "distribution": "Dağılım",
    }

    context_info = ""
    is_followup = reference_context.get("is_followup", False)
    if is_followup:
        prev_entities = reference_context.get("previous_entities", [])
        if prev_entities:
            context_info = f"\n\nÖnceki sonuçlar: {', '.join(str(e) for e in prev_entities[:3])}"

    message = (
        f'Sorgunuz: "{user_message}"\n\n'
        f"Sorgu türü belirsiz (güven: {query_type_confidence:.0%}). "
        f"Hangi analiz türünü istiyorsunuz?{context_info}\n\n"
        "Seçenekler:\n"
        + "\n".join(f"- **{k}**: {v}" for k, v in options.items())
    )

    user_choice = interrupt({
        "message": message,
        "type": "query_type_clarification",
        "options": list(options.keys()),
    })

    logger.info(f"[HITL] User selected: {user_choice}")

    return {
        "_query_type": user_choice,
        "_query_type_confidence": 1.0,
        "_needs_clarification": False,
        "user_clarification": user_choice,
    }


# =============================================================================
# NODE 6: process_clarification_node
# =============================================================================

async def process_clarification_node(state: ClassifyState) -> Dict[str, Any]:
    """
    Process user clarification response (Enhanced HITL v2.0).

    Routes to type-specific processor based on ambiguity_context.
    Falls back to legacy system if no ambiguity_context.

    Migrated from process_user_clarification_node() + all _process_*_clarification()
    helpers in nodes.py.
    """
    user_response = state.get("user_clarification")
    pending_question = state.get("_pending_question")

    if not user_response:
        logger.warning("[PROCESS_CLAR] No user clarification found")
        return {}

    logger.info(f"[PROCESS_CLAR] Processing clarification: {user_response}")

    # Enhanced HITL
    ambiguity_ctx = state.get("_ambiguity_context")
    if ambiguity_ctx:
        logger.info(f"[PROCESS_CLAR] Enhanced processing for {ambiguity_ctx.ambiguity_type}")
        return await _process_enhanced_clarification(state, ambiguity_ctx, user_response)

    # Legacy HITL
    logger.info("[PROCESS_CLAR] Using legacy clarification processing")
    return _process_legacy_clarification(state, user_response, pending_question)


async def _process_enhanced_clarification(
    state: ClassifyState,
    ambiguity_ctx: Any,
    user_response: str
) -> Dict[str, Any]:
    """
    Process user clarification using enhanced ambiguity system.
    Routes to type-specific processor based on ambiguity_type.
    """
    from src.graphs.report.ambiguity_framework import AmbiguityType

    result: Dict[str, Any] = {
        "_pending_question": None,
        "user_clarification": None,
        "_ambiguity_context": None,  # Clear after processing
    }

    ambiguity_type = ambiguity_ctx.ambiguity_type

    if ambiguity_type == AmbiguityType.CONTEXT:
        updates = _process_context_clarification(state, ambiguity_ctx, user_response)
    elif ambiguity_type == AmbiguityType.PROMPT_SCOPE:
        updates = _process_prompt_scope_clarification(state, ambiguity_ctx, user_response)
    elif ambiguity_type == AmbiguityType.INTENT:
        updates = _process_intent_clarification(state, ambiguity_ctx, user_response)
    elif ambiguity_type == AmbiguityType.COLUMN:
        updates = _process_column_clarification(state, ambiguity_ctx, user_response)
    elif ambiguity_type == AmbiguityType.VALUE:
        updates = _process_value_clarification(state, ambiguity_ctx, user_response)
    else:
        logger.warning(f"[PROCESS_CLAR] Unknown ambiguity type: {ambiguity_type}")
        updates = {"_intent_type": "new_query"}

    return {**result, **updates}


def _process_context_clarification(
    state: ClassifyState,
    ambiguity_ctx: Any,
    user_response: str
) -> Dict[str, Any]:
    """
    Process context ambiguity clarification (MOST CRITICAL).

    User choice:
    - Option 1 (keep filters): execution_mode=delta, intent=modify_filter
    - Option 2 (clear filters): clear context, intent=new_query
    """
    response_lower = user_response.lower()
    keep_filters = False

    if "1" in user_response or "evet" in response_lower or "koru" in response_lower:
        keep_filters = True
    elif "2" in user_response or "hayır" in response_lower or "tüm" in response_lower:
        keep_filters = False
    else:
        logger.warning(f"[PROCESS_CLAR] Unclear response: '{user_response}', defaulting to keep filters")
        return {
            "_intent_type": "modify_filter",
            "_needs_clarification": False,
        }

    if keep_filters:
        logger.info("[PROCESS_CLAR] User chose to KEEP filters")
        active_context = state.get("active_context")

        if not active_context:
            logger.warning("[PROCESS_CLAR] No active context to keep, treating as new query")
            return {
                "_intent_type": "new_query",
                "_needs_clarification": False,
            }

        return {
            "_intent_type": "modify_filter",
            "_needs_clarification": False,
        }
    else:
        logger.info("[PROCESS_CLAR] User chose to CLEAR filters (new query)")
        return {
            "_intent_type": "new_query",
            "_needs_clarification": False,
        }


def _process_prompt_scope_clarification(
    state: ClassifyState,
    ambiguity_ctx: Any,
    user_response: str
) -> Dict[str, Any]:
    """Process prompt scope ambiguity clarification."""
    option_mapping = {
        "1": "list_all",
        "2": "summary_stats",
        "3": "filtered",
        "4": "grouped"
    }

    scope_type = "list_all"
    for key, value in option_mapping.items():
        if key in user_response:
            scope_type = value
            break

    original_query = state.get("_user_query", "")
    if scope_type == "list_all":
        enhanced_query = f"{original_query} - tüm kayıtları listele"
    elif scope_type == "summary_stats":
        enhanced_query = f"{original_query} - özet istatistikler"
    elif scope_type == "filtered":
        enhanced_query = f"{original_query} - filtreli analiz"
    elif scope_type == "grouped":
        enhanced_query = f"{original_query} - gruplama ile analiz"
    else:
        enhanced_query = original_query

    logger.info(f"[PROCESS_CLAR] Prompt scope clarified: {scope_type}")

    return {
        "_intent_type": "new_query",
        "_user_query": enhanced_query,
        "_needs_clarification": False,
    }


def _process_intent_clarification(
    state: ClassifyState,
    ambiguity_ctx: Any,
    user_response: str
) -> Dict[str, Any]:
    """Process intent ambiguity clarification."""
    response_lower = user_response.lower()

    if "yeni" in response_lower or "oluştur" in response_lower or "1" in user_response:
        intent_type = "new_query"
    elif "değiştir" in response_lower or "filtre" in response_lower or "2" in user_response:
        intent_type = "modify_filter"
    elif "kolon" in response_lower or "ekle" in response_lower or "3" in user_response:
        intent_type = "modify_columns"
    elif "geri" in response_lower or "undo" in response_lower:
        intent_type = "rollback"
    else:
        intent_type = "new_query"

    logger.info(f"[PROCESS_CLAR] Intent clarified: {intent_type}")
    return {
        "_intent_type": intent_type,
        "_needs_clarification": False,
    }


def _process_column_clarification(
    state: ClassifyState,
    ambiguity_ctx: Any,
    user_response: str
) -> Dict[str, Any]:
    """Process column ambiguity clarification."""
    candidates = ambiguity_ctx.candidates
    selected_column = None

    for i, candidate in enumerate(candidates, 1):
        if str(i) in user_response:
            selected_column = candidate
            break

    if not selected_column:
        selected_column = user_response.strip()

    logger.info(f"[PROCESS_CLAR] Column clarified: {selected_column}")
    return {
        "_selected_column": selected_column,
        "_clarification_type": "column",
        "_intent_type": "retry_with_clarification",
        "_needs_clarification": False,
    }


def _process_value_clarification(
    state: ClassifyState,
    ambiguity_ctx: Any,
    user_response: str
) -> Dict[str, Any]:
    """Process value ambiguity clarification."""
    candidates = ambiguity_ctx.candidates
    selected_value = None

    for i, candidate in enumerate(candidates, 1):
        if str(i) in user_response:
            selected_value = candidate
            break

    if not selected_value:
        selected_value = user_response.strip()

    logger.info(f"[PROCESS_CLAR] Value clarified: {selected_value}")
    return {
        "_selected_value": selected_value,
        "_clarification_type": "value",
        "_intent_type": "retry_with_clarification",
        "_needs_clarification": False,
    }


def _process_legacy_clarification(
    state: ClassifyState,
    user_response: str,
    pending_question: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Process clarification using legacy system (backward compatibility).

    Migrated from _process_legacy_clarification() in nodes.py with
    state field names adapted for ClassifyState.
    """
    from src.graphs.report.intent import IntentType

    response_lower = user_response.lower()
    result: Dict[str, Any] = {
        "_pending_question": None,
        "user_clarification": None,
        "_needs_clarification": False,
    }

    question_context = pending_question.get("context", "") if pending_question else ""
    question_text = pending_question.get("question", "") if pending_question else ""

    # USER PREFERENCES
    if "tercihleri" in question_text or "tercihleriniz" in question_text:
        logger.info(f"[PROCESS_CLAR] User preference received: {user_response}")
        result["_user_preference"] = user_response
        result["_preference_type"] = (
            "date_range"
            if ("gün" in user_response or "ay" in user_response or "yıl" in user_response)
            else "general"
        )
        result["_intent_type"] = "new_query"
        return result

    # "DID YOU MEAN"
    if "demek istediniz" in question_text or "kullanılsın mı" in question_text:
        logger.info(f"[PROCESS_CLAR] 'Did you mean' clarification received: {user_response}")
        if "evet" in response_lower or "doğru" in response_lower:
            if pending_question:
                question_parts = pending_question.get("question", "").split("'")
                if len(question_parts) >= 4:
                    suggested_value = question_parts[3]
                    result["_selected_value"] = suggested_value
                    result["_clarification_type"] = "value"
                    result["_intent_type"] = "retry_with_clarification"
                    logger.info(f"[PROCESS_CLAR] User accepted suggestion: {suggested_value}")
        else:
            result["_use_exact_input"] = True
            result["_intent_type"] = "new_query"
            logger.info("[PROCESS_CLAR] User rejected suggestion, using exact input")
        return result

    # COLUMN AMBIGUITY
    if "için hangi kolonu" in question_text or "birden fazla kolon" in question_context:
        logger.info(f"[PROCESS_CLAR] Column ambiguity clarification received: {user_response}")
        result["_selected_column"] = user_response
        result["_clarification_type"] = "column"
        result["_intent_type"] = "retry_with_clarification"
        return result

    # VALUE AMBIGUITY
    if "için hangi değeri" in question_text or "için birden fazla eşleşme" in question_context:
        logger.info(f"[PROCESS_CLAR] Value ambiguity clarification received: {user_response}")
        result["_selected_value"] = user_response
        result["_clarification_type"] = "value"
        result["_intent_type"] = "retry_with_clarification"
        return result

    # EMPTY RESULT RECOVERY
    if "boş sonuç" in question_context.lower() or "veri bulunamadı" in question_context.lower():
        if "geri" in response_lower or "önceki" in response_lower:
            result["_intent_type"] = IntentType.ROLLBACK.value
            logger.info("[PROCESS_CLAR] User chose rollback after empty result")
        elif "genişlet" in response_lower or "filtre" in response_lower:
            result["_intent_type"] = IntentType.MODIFY_FILTER.value
            result["_modification_action"] = "expand_filter"
            logger.info("[PROCESS_CLAR] User chose to expand filter")
        else:
            result["_intent_type"] = IntentType.NEW_QUERY.value
            logger.info("[PROCESS_CLAR] User chose new query")
        return result

    # TABLE AMBIGUITY
    if "hangi tablo" in question_context.lower():
        result["_selected_table"] = user_response
        result["_intent_type"] = IntentType.NEW_QUERY.value
        logger.info(f"[PROCESS_CLAR] User selected table: {user_response}")
        return result

    # FILTER VALUE AMBIGUITY
    if "hangi değer" in question_context.lower() or "için birden fazla" in question_context.lower():
        result["_selected_filter_value"] = user_response
        result["_intent_type"] = IntentType.MODIFY_FILTER.value
        logger.info(f"[PROCESS_CLAR] User selected filter value: {user_response}")
        return result

    # MODIFICATION TYPE AMBIGUITY
    if "nasıl değiştirmek" in question_context.lower():
        if "filtre ekle" in response_lower:
            result["_intent_type"] = IntentType.MODIFY_FILTER.value
            result["_modification_action"] = "add"
        elif "filtre çıkar" in response_lower:
            result["_intent_type"] = IntentType.MODIFY_FILTER.value
            result["_modification_action"] = "remove"
        elif "gruplama" in response_lower:
            result["_intent_type"] = IntentType.MODIFY_AGGREGATION.value
        elif "sıralama" in response_lower:
            result["_intent_type"] = IntentType.MODIFY_ORDER.value
        elif "yeni" in response_lower:
            result["_intent_type"] = IntentType.NEW_QUERY.value
        else:
            result["_intent_type"] = IntentType.NEW_QUERY.value
        return result

    # GENERAL FALLBACK
    if "yeni" in response_lower or "oluştur" in response_lower:
        result["_intent_type"] = IntentType.NEW_QUERY.value
    elif "değiştir" in response_lower or "ekle" in response_lower:
        result["_intent_type"] = IntentType.MODIFY_FILTER.value
    elif "geri" in response_lower or "önceki" in response_lower:
        result["_intent_type"] = IntentType.ROLLBACK.value
    else:
        result["_intent_type"] = IntentType.NEW_QUERY.value

    return result


# =============================================================================
# NODE 7: build_classify_result_node
# =============================================================================

async def build_classify_result_node(state: ClassifyState) -> Dict[str, Any]:
    """
    Assemble ClassifyResult from all internal state fields.
    This is the terminal node of the classify agent.
    """
    intent_type = state.get("_intent_type") or "new_query"
    confidence = state.get("_confidence") or 0.5
    query_type = state.get("_query_type") or "aggregation"
    query_type_confidence = state.get("_query_type_confidence") or 0.0
    needs_clarification = state.get("_needs_clarification") or False
    pending_question = state.get("_pending_question")
    user_query = state.get("_user_query") or state.get("user_input") or ""
    reference_context = state.get("_reference_context") or {}
    extracted_entities = state.get("_extracted_entities") or {}

    # Clean internal fields from entities before storing
    clean_entities = {
        k: v for k, v in extracted_entities.items()
        if not k.startswith("_")
    }

    result: ClassifyResult = {
        "intent_type": intent_type,
        "query_type": query_type,
        "confidence": confidence,
        "needs_clarification": needs_clarification,
        "pending_question": pending_question,
        "user_query": user_query,
        "entities": clean_entities if clean_entities else None,
        "reference_context": reference_context if reference_context else None,
    }

    logger.info(f"[BUILD_RESULT] ClassifyResult assembled: "
                f"intent={intent_type}, query_type={query_type}, "
                f"confidence={confidence:.2f}, needs_clarification={needs_clarification}")

    return {"classify_result": result}


# =============================================================================
# ROUTING
# =============================================================================

def route_after_ambiguity(state: ClassifyState) -> str:
    """
    Route after detect_ambiguity.

    - If max clarifications reached → build_result (avoid loop)
    - If clarification needed → hitl_clarification
    - Otherwise → build_result
    """
    if state.get("clarification_count", 0) >= HITL_CONFIG.get("max_clarifications", 3):
        logger.info("[ROUTE] Max clarifications reached, routing to build_result")
        return "build_result"

    if state.get("_needs_clarification"):
        logger.info("[ROUTE] Clarification needed, routing to hitl_clarification")
        return "hitl_clarification"

    logger.info("[ROUTE] No clarification needed, routing to build_result")
    return "build_result"


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_classify_agent(llm=None):
    """
    Build and compile the classify agent graph.

    Args:
        llm: Optional language model. If None, rule-based path is used.

    Returns:
        Compiled LangGraph StateGraph.
    """
    # Build node functions with captured llm
    classify_intent_node = _make_classify_intent_node(llm)
    detect_references_node = _make_detect_references_node(llm)
    validate_entities_node = _make_validate_entities_node(llm)
    detect_ambiguity_node = _make_detect_ambiguity_node(llm)

    graph = StateGraph(ClassifyState)

    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("detect_references", detect_references_node)
    graph.add_node("validate_entities", validate_entities_node)
    graph.add_node("detect_ambiguity", detect_ambiguity_node)
    graph.add_node("hitl_clarification", hitl_clarification_node)
    graph.add_node("process_clarification", process_clarification_node)
    graph.add_node("build_result", build_classify_result_node)

    graph.add_edge(START, "classify_intent")

    # Fan-out: both run in parallel after classify_intent
    graph.add_edge("classify_intent", "detect_references")
    graph.add_edge("classify_intent", "validate_entities")

    # Fan-in: detect_ambiguity waits for BOTH
    graph.add_edge("detect_references", "detect_ambiguity")
    graph.add_edge("validate_entities", "detect_ambiguity")

    graph.add_conditional_edges("detect_ambiguity", route_after_ambiguity, {
        "hitl_clarification": "hitl_clarification",
        "build_result": "build_result",
    })
    graph.add_edge("hitl_clarification", "process_clarification")
    graph.add_edge("process_clarification", "classify_intent")  # loop back
    graph.add_edge("build_result", END)

    return graph.compile()
