"""
Report Graph Nodes

Stateful Report Agent node fonksiyonları.

Graph Flow:
    START → classify_intent → [decision] → process_query → check_results → visualization → build_response → END
                                  ↓
                           [ask_user] (interrupt_before)
                                  ↓
                            process_response
"""

import logging
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.language_models import BaseChatModel

from .state import (
    ReportState,
    ActiveQueryContext,
    create_checkpoint,
    create_empty_context
)
from .intent import IntentClassifier, IntentClassification, IntentType, SimpleIntentClassifier
from .tools import HITLQuestions, create_clarification_request
from .delta_parser import AdvancedDeltaParser, SQLModifier
from .ambiguity_detectors import create_intent_detector, create_metadata_detector
from .hitl_question_builder import HITLQuestionBuilder
from .ambiguity_router import (
    AmbiguityRouter,
    AmbiguityFallback,
    should_trigger_hitl,
    apply_auto_resolution
)

logger = logging.getLogger(__name__)


# =============================================================================
# ENHANCED HITL CONFIGURATION
# =============================================================================

def _load_hitl_config() -> Dict[str, Any]:
    """
    Load enhanced HITL configuration from config.yaml.

    Returns default values if config not found or parsing fails.

    Returns:
        Dict with HITL configuration
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

        # Merge with defaults
        defaults = _get_default_hitl_config()
        return {**defaults, **hitl_config}

    except Exception as e:
        logger.error(f"[HITL_CONFIG] Error loading config: {e}, using defaults")
        return _get_default_hitl_config()


def _get_default_hitl_config() -> Dict[str, Any]:
    """
    Get default HITL configuration.

    Returns:
        Dict with default values
    """
    return {
        "enable_enhanced_hitl": True,
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

# Simple in-memory metrics (for monitoring)
HITL_METRICS = {
    "ambiguity_distribution": {},     # {ambiguity_type: count}
    "auto_resolve_count": 0,          # Total auto-resolved
    "hitl_trigger_count": 0,          # Total HITL triggered
    "clarification_counts": [],       # List of clarification counts per session
}


def _track_ambiguity_metric(ambiguity_type: str, event: str = "detected") -> None:
    """
    Track ambiguity metrics for monitoring.

    Args:
        ambiguity_type: Type of ambiguity (CONTEXT, PROMPT_SCOPE, etc.)
        event: Event type (detected, auto_resolved, user_resolved)
    """
    try:
        monitoring_config = HITL_CONFIG.get("monitoring", {})
        track_distribution = monitoring_config.get("track_ambiguity_distribution", True)

        if not track_distribution:
            return

        # Track distribution
        key = f"{ambiguity_type}_{event}"
        HITL_METRICS["ambiguity_distribution"][key] = \
            HITL_METRICS["ambiguity_distribution"].get(key, 0) + 1

        # Track totals
        if event == "auto_resolved":
            HITL_METRICS["auto_resolve_count"] += 1
        elif event == "detected":
            HITL_METRICS["hitl_trigger_count"] += 1

        # Log every 10 events
        total_events = sum(HITL_METRICS["ambiguity_distribution"].values())
        if total_events % 10 == 0:
            logger.info(f"[HITL_METRICS] Distribution: {HITL_METRICS['ambiguity_distribution']}")
            logger.info(f"[HITL_METRICS] Auto-resolve rate: {_calculate_auto_resolve_rate():.2%}")

    except Exception as e:
        logger.error(f"[HITL_METRICS] Error tracking metric: {e}")


def _calculate_auto_resolve_rate() -> float:
    """
    Calculate auto-resolution success rate.

    Returns:
        Rate (0.0-1.0)
    """
    total = HITL_METRICS["hitl_trigger_count"]
    auto_resolved = HITL_METRICS["auto_resolve_count"]

    if total == 0:
        return 0.0

    return auto_resolved / total


def get_hitl_metrics() -> Dict[str, Any]:
    """
    Get current HITL metrics for monitoring dashboard.

    Returns:
        Dict with metrics
    """
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
# VISUALIZATION DECISION (Moved from data_visualization graph)
# =============================================================================

async def decide_visualization_node(state: ReportState) -> Dict[str, Any]:
    """
    Görselleştirme kararı ver (Phase 2 Enhanced: query_type driven).

    Decision Priority:
    1. User explicit request (grafik olarak, çubuk grafik, etc.)
    2. query_type mapping (PRIORITY - Phase 2 ✓)
    3. Data shape analysis (fallback)
    4. Default (table/list)

    IMPORTANT: Supports both "visualize_direct" and "normal" paths:
    - visualize_direct: Uses active_query_context.result_sample
    - normal: Uses text2sql_output.results

    Phase 2 Changes:
    - Uses QUERY_TYPE_VIZ_MAPPING for intelligent chart selection
    - Automatically shows graphs for query types that benefit from visualization
    - Respects query_type patterns (ranking → bar, time_series → line, etc.)
    """
    # Import Phase 2 visualization mapping
    from .query_type_viz_mapping import (
        get_viz_config,
        format_viz_decision,
        analyze_data_shape
    )

    # Check if this is visualize_direct path (no text2sql_output)
    text2sql_output = state.get("text2sql_output")
    active_context = state.get("active_query_context")
    query_type = state.get("query_type")

    # Get results from appropriate source
    results = None
    if text2sql_output and not text2sql_output.get("error"):
        results = text2sql_output.get("results", [])
        logger.debug("[REPORT] Using results from text2sql_output")
    elif active_context and active_context.get("result_sample"):
        results = active_context.get("result_sample", [])
        logger.info("[REPORT] [VISUALIZE_DIRECT] Using results from active_query_context")
    else:
        logger.warning("[REPORT] No results available for visualization decision")
        return {}

    if not results or len(results) == 0:
        logger.info("[REPORT] No results for visualization")
        return {
            "_viz_decision": {
                "needs_graph": False,
                "output_type": "table",
                "reason": "Sonuç yok"
            }
        }

    # Analyze data shape (for fallback)
    data_shape = analyze_data_shape(results)

    # Quick decision: Single value
    if data_shape["is_single_value"]:
        logger.info("[REPORT] Single value detected, no graph needed")
        return {
            "_viz_decision": {
                "needs_graph": False,
                "output_type": "single_value",
                "reason": "Tek değer sonucu",
                "data_shape": data_shape
            }
        }

    # PRIORITY 1: Check user query for EXPLICIT chart type request
    # Only trigger if user explicitly mentions a CHART TYPE (not just query semantics)
    user_query = get_last_user_message(state) or ""
    user_query_lower = user_query.lower()

    # Explicit chart type keywords - Two-step matching:
    # 1. Exact phrase match (e.g., "çubuk grafik")
    # 2. Flexible match: chart type name + "grafik" indicator (handles Turkish suffixes)

    # Chart type base names
    chart_names = {
        "bar": ["çubuk", "막대", "bar"],
        "line": ["çizgi", "line"],
        "pie": ["pasta", "pie", "daire"],
        "scatter": ["scatter", "nokta", "saçılım"],
        "sunburst": ["sunburst", "hiyerarşik"],
        "treemap": ["treemap", "ağaç"]
    }

    # Indicators that user is requesting a chart
    chart_indicators = ["grafik", "chart", "olarak", "ver", "yap", "göster"]

    detected_chart_type = None

    # Check each chart type
    for chart_type, names in chart_names.items():
        # Check if any chart name + chart indicator combo exists
        for name in names:
            # Check for chart name presence
            if name in user_query_lower:
                # Check if any chart indicator also present (for explicit chart request)
                if any(indicator in user_query_lower for indicator in chart_indicators):
                    detected_chart_type = f"{chart_type}_chart"
                    logger.info(f"[REPORT] [PRIORITY 1] User explicitly requested: {detected_chart_type} ('{name}' + chart indicator)")
                    break

        if detected_chart_type:
            break

    if detected_chart_type:
        # User override - but still use query_type config if available
        if query_type:
            viz_decision = format_viz_decision(
                query_type=query_type,
                override_chart_type=detected_chart_type,
                data_shape=data_shape
            )
            viz_decision["reasoning"] = f"Kullanıcı {detected_chart_type} istedi (query_type: {query_type})"
        else:
            viz_decision = {
                "needs_graph": True,
                "output_type": detected_chart_type,
                "chart_type": detected_chart_type,
                "reasoning": f"Kullanıcı {detected_chart_type} istedi",
                "query_type_driven": False,
                "data_shape": data_shape
            }

        return {"_viz_decision": viz_decision}

    # PRIORITY 2: query_type mapping (Phase 2 ✓)
    if query_type:
        logger.info(f"[REPORT] [PHASE2] [PRIORITY 2] Using query_type={query_type} for viz decision")

        viz_decision = format_viz_decision(
            query_type=query_type,
            data_shape=data_shape
        )

        logger.info(f"[REPORT] [PHASE2] Query type decision: {viz_decision['output_type']} "
                   f"(needs_graph={viz_decision['needs_graph']})")

        return {"_viz_decision": viz_decision}

    # PRIORITY 3: Data shape analysis (fallback when no query_type)
    logger.info("[REPORT] [PRIORITY 3] No query_type, using data shape analysis")

    if data_shape["is_time_series"] and data_shape["row_count"] > 2:
        # Time series data → line chart
        viz_decision = {
            "needs_graph": True,
            "output_type": "line_chart",
            "chart_type": "line_chart",
            "reasoning": "Zaman serisi verisi tespit edildi",
            "query_type_driven": False,
            "data_shape": data_shape
        }
    elif data_shape["row_count"] <= 10 and data_shape["column_count"] == 2:
        # Small categorical data → bar chart
        viz_decision = {
            "needs_graph": True,
            "output_type": "bar_chart",
            "chart_type": "bar_chart",
            "reasoning": "Küçük kategorik veri (bar chart uygun)",
            "query_type_driven": False,
            "data_shape": data_shape
        }
    elif data_shape["row_count"] <= 20:
        # Small result set → simple list (no graph)
        viz_decision = {
            "needs_graph": False,
            "output_type": "simple_list",
            "reasoning": "Küçük sonuç seti (liste gösterimi)",
            "query_type_driven": False,
            "data_shape": data_shape
        }
    else:
        # Large result set → table
        viz_decision = {
            "needs_graph": False,
            "output_type": "table",
            "reasoning": "Büyük sonuç seti (tablo gösterimi)",
            "query_type_driven": False,
            "data_shape": data_shape
        }

    logger.info(f"[REPORT] Data shape decision: {viz_decision['output_type']} "
               f"(needs_graph={viz_decision['needs_graph']})")

    return {"_viz_decision": viz_decision}


# =============================================================================
# EXISTING NODE FUNCTIONS
# =============================================================================


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def _detect_references_llm(
    user_message: str,
    llm: BaseChatModel,
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
    # Build context
    context_info = "Yok"
    if conversation_history and len(conversation_history) > 0:
        last_query = conversation_history[-1].get("query", "")
        context_info = f"Önceki sorgu: {last_query}"

    # LLM prompt for reference detection
    prompt = f"""Kullanıcının sorgusu önceki sonuçlara referans veriyor mu?

Kullanıcı Sorusu: {user_message}
Context: {context_info}

ÖNEMLI:
- "bu şubeler", "onlar", "bunları" → önceki sonuçlara referans
- "bu ay", "bu yıl" → zaman referansı, önceki sonuç DEĞİL
- "en çok satan" → YENİ sorgu, referans DEĞİL

JSON döndür (sadece JSON):
{{
    "has_reference": true,
    "reference_type": "previous_results",
    "confidence": 0.9,
    "reasoning": "Kullanıcı 'bu şubeler' diyerek önceki sorguya atıfta bulunuyor"
}}

reference_type seçenekleri:
- "previous_results": Önceki sorgu sonuçlarına referans
- "time": Zaman referansı (bu ay, bu yıl)
- "none": Referans yok"""

    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        # Extract JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        import json
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
        # Fallback: assume no reference (safe default)
        return {
            "has_reference": False,
            "reference_type": "none",
            "confidence": 0.0,
            "needs_context": False,
            "reasoning": "JSON parse error - fallback to no reference"
        }
    except Exception as e:
        logger.error(f"[REFERENCE_LLM] Error: {e}")
        # Fallback: assume no reference
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
    llm: BaseChatModel
) -> Dict[str, Any]:
    """
    LLM-driven context-aware query analysis.

    CRITICAL: ALL NLP is LLM-driven!
    - Reference detection (LLM)
    - Query type classification (LLM)
    - Ambiguity detection (LLM)

    Args:
        user_message: User's query
        active_context: Active query context
        conversation_history: Previous queries
        last_query_results: Last query results
        llm: Language model

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

        # Extract entities from previous results
        prev_entities = []
        if prev_results and len(prev_results) > 0:
            first_key = list(prev_results[0].keys())[0]
            prev_entities = [r.get(first_key) for r in prev_results[:5]]

        previous_context = f"""
Önceki Sorgu: "{prev_query}"
Query Type: {prev_type}
Sonuçlar: {prev_entities}
Kullanıcı bu sonuçlara referans veriyor.
"""
        context_parts.append(f"Önceki sorgu: {prev_type}")

    # 3. LLM prompt for query type classification
    prompt = f"""Kullanıcının sorgu türünü tespit et.

Soru: {user_message}
Context: {' | '.join(context_parts) if context_parts else 'Yok'}
Referans: {'EVET - önceki sonuçları kullanmalı' if is_followup else 'YOK'}

{previous_context if is_followup else ''}

⚠️ KRİTİK: ZAMAN FİLTRESİ ≠ ZAMAN GRANULARİTY
- "Son 1 yılda A vs B" → comparison (sadece zaman filtresi)
- "A ve B'nin aylık karşılaştırması" → time_series_comparison (zaman granularity)

Query Types:

1. **single_value** - TEK bir toplam/ortalama/sayı değeri
   ⚠️ KRİTİK İŞARETLER:
   - "Toplam", "Toplamı", "Toplam ne", "Toplam kaç"
   - "Ortalama", "Ortalaması"
   - "Kaç tane", "Ne kadar", "Miktar"
   - "Maksimum", "Minimum", "En yüksek değer", "En düşük değer" (TEK DEĞER isteniyorsa)
   - GRUPLAMA YOK, SIRALAMA YOK, sadece TEK SAYISAL SONUÇ

   ✅ DOĞRU ÖRNEKLER:
   - "Toplam ciro nedir?" → single_value (tek değer: 1.250.000 TL)
   - "Toplam ciro" → single_value
   - "Ortalama sipariş tutarı" → single_value
   - "Kaç müşterimiz var?" → single_value
   - "Ne kadar satış yaptık?" → single_value (toplam satış)
   - "Toplam kaç sipariş var?" → single_value

   ❌ YANLIŞ:
   - "En çok ciro yapan 10 şube" → ranking (sıralama var!)
   - "Kategorilere göre toplam" → aggregation (gruplama var!)

2. **ranking** - Top-N sıralama (en yüksek/düşük değerler)
   ⚠️ KRİTİK İŞARETLER:
   - "En çok", "En az", "En yüksek", "En düşük"
   - "Top", "İlk", "Son"
   - Sayı belirtimi: "10 ürün", "5 şube"

   ✅ ÖRNEKLER:
   - "En çok satan 10 ürün" → ranking
   - "En az ciro yapan 5 şube" → ranking
   - "Top 3 kategori" → ranking

3. **comparison** - Karşılaştırma (2+ entity)
   ⚠️ ÖNEMLİ: TEK bir zaman noktası veya dönem için karşılaştırma
   ⚠️ ZAMAN GRANULARİTY ifadesi YOKSA → comparison
   ⚠️ Zaman FİLTRESİ olabilir ama zaman GRANULARİTY (aylık, günlük) OLMAMALI

   ✅ ÖRNEKLER:
   - "İstanbul vs Ankara" → comparison
   - "İstanbul ile Ankara satışları" → comparison (zaman granularity yok)
   - "Son 1 yılda dürümler ve içecekler karşılaştırması" → comparison (zaman filtresi var ama granularity yok!)
   - "2024'te A ve B karşılaştırması" → comparison (zaman filtresi var ama aylık/günlük gibi granularity yok)

4. **time_series** - Zaman serisi
   ⚠️ TEK entity'nin zaman içindeki değişimi

   ✅ ÖRNEKLER:
   - "Son 6 aydaki satışlar" → time_series (tek entity)

5. **time_series_comparison** - Çoklu zaman serisi
   ⚠️ KRİTİK: BİRDEN FAZLA entity + ZAMAN GRANULARİTY → time_series_comparison
   ⚠️ ZAMAN FİLTRESİ vs ZAMAN GRANULARİTY FARKI:
      - "Son 1 yılda A vs B" → comparison (zaman filtresi, granularity YOK!)
      - "A ve B'nin aylık karşılaştırması" → time_series_comparison (zaman granularity VAR!)
   ⚠️ STRONG INDICATORS: "aylık bazda", "günlük", "ay ay", "haftalık", "her ay",
      "aylara göre", "günlere göre", "ay bazında", "gün bazında", "hafta bazında"
      + karşılaştırma ifadeleri ("ile kıyasla", "karşılaştır", "vs")

   ✅ ÖRNEKLER:
   - "X ve Y'nin aylık satışları" → time_series_comparison (2 entity + aylık)
   - "Bu iki kategoriyi aylık bazda karşılaştır" → time_series_comparison
   - "A ve B'nin son 6 aydaki AY AY karşılaştırması" → time_series_comparison

   ❌ YANLIŞ:
   - "Son 1 yılda dürümler vs içecekler" → time_series_comparison DEĞİL! comparison (zaman filtresi var ama granularity yok)

6. **aggregation** - Gruplama

   ✅ ÖRNEKLER:
   - "Kategorilere göre toplam" → aggregation

7. **distribution** - Dağılım

   ✅ ÖRNEKLER:
   - "Satışların dağılımı" → distribution

8. **trend** - Trend analizi

   ✅ ÖRNEKLER:
   - "Satışlar artıyor mu?" → trend

KRİTİK KURAL - single_value vs ranking vs aggregation:
- "Toplam X" (GRUPLAMA YOK) → single_value ✅
- "En çok X yapan 10 Y" → ranking ✅
- "Y'lere göre X toplam" → aggregation ✅

KRİTİK KURAL - ZAMAN GRANULARİTY TESPİTİ:
- Kullanıcı "aylık", "günlük", "haftalık", "yıllık", "ay ay", "gün gün" gibi
  ifadeler kullandıysa VE 2+ entity karşılaştırıyorsa
  → query_type MUTLAKA "time_series_comparison" OLMALI!

JSON döndür (sadece JSON):
{{
    "query_type": "ranking",
    "confidence": 0.9,
    "needs_clarification": false,
    "reasoning": "Kullanıcı top-N sıralama istiyor"
}}

ÖNEMLI: Eğer sorgu belirsizse (confidence < 0.65), needs_clarification: true yap."""

    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        # Extract JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        import json
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
            logger.warning(f"[QUERY_ANALYSIS] Valid types: {valid_types}")
            logger.info(f"[QUERY_ANALYSIS] Asking LLM to map invalid query_type to valid type...")

            # LLM-driven mapping: Ask LLM to correct the query_type
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

                # Extract JSON
                if "```json" in correction_content:
                    correction_content = correction_content.split("```json")[1].split("```")[0].strip()
                elif "```" in correction_content:
                    correction_content = correction_content.split("```")[1].split("```")[0].strip()

                correction_data = json.loads(correction_content)
                corrected_type = correction_data.get("corrected_query_type", "aggregation")

                if corrected_type in valid_types:
                    logger.info(f"[QUERY_ANALYSIS] LLM corrected '{query_type}' → '{corrected_type}'")
                    query_type = corrected_type
                    # LLM successfully corrected → boost confidence to avoid ask_user
                    # If original confidence was low, raise it above ambiguity threshold (0.7)
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

        # Log final query_type
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
            "needs_clarification": True,  # Parse error → ask user
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


def get_last_user_message(state: ReportState) -> Optional[str]:
    """State'den son kullanıcı mesajını al."""
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content
    return None


def update_active_context(
    current_context: Optional[ActiveQueryContext],
    text2sql_output: Dict[str, Any]
) -> ActiveQueryContext:
    """
    Text2SQL çıktısından active context güncelle.

    Text2SQL output format:
    - sql_queries: List[str] - Generated SQL queries
    - results: List[dict] - Query results
    - parsed_intent: dict - Parsed intent with steps
    - resolved_steps: List[dict] - Steps with resolved values
    """
    # SQL bilgilerini al
    sql_queries = text2sql_output.get("sql_queries", [])
    results = text2sql_output.get("results", [])

    # parsed_intent veya resolved_steps'tan detayları çek
    parsed_intent = text2sql_output.get("parsed_intent", {})
    resolved_steps = text2sql_output.get("resolved_steps", [])

    # Filters, grouping, ordering bilgilerini çıkar
    applied_filters = []
    grouping_columns = []
    order_by_columns = []

    # resolved_steps varsa oradan al (daha güncel)
    steps = resolved_steps if resolved_steps else parsed_intent.get("steps", [])

    for step in steps:
        # Filters
        step_filters = step.get("filters", [])
        for f in step_filters:
            filter_info = {
                "column": f.get("field_hint", ""),
                "operator": f.get("operator", "="),
                "value": f.get("resolved_value") or f.get("value_hint", "")
            }
            applied_filters.append(filter_info)

        # Group by
        step_group_by = step.get("group_by", [])
        grouping_columns.extend(step_group_by)

        # Order by
        step_order_by = step.get("order_by")
        if step_order_by:
            order_col = step_order_by.get("field_hint", "")
            order_dir = step_order_by.get("direction", "ASC")
            if order_col:
                order_by_columns.append(f"{order_col} {order_dir}")

    # Tablo adını tespit et
    table_name = "MasterReportDocumentTable"  # Default

    # 1. Önce schema_metadata'dan almayı dene
    schema_metadata = text2sql_output.get("schema_metadata", {})
    if schema_metadata and isinstance(schema_metadata, dict):
        # İlk key'i tablo adı olarak kullan
        table_keys = list(schema_metadata.keys())
        if table_keys:
            table_name = table_keys[0]

    # 2. SQL query'den tablo adını parse etmeyi dene
    if sql_queries and not table_name:
        first_sql = sql_queries[0].upper()
        # "FROM TableName" pattern'ini ara
        import re
        from_match = re.search(r'\bFROM\s+(\w+)', first_sql)
        if from_match:
            table_name = from_match.group(1)

    # Result sample oluştur (ilk 5 satır)
    result_sample = None
    if results:
        result_sample = results[:5]

    logger.info(f"[REPORT] Updating context: SQL={len(sql_queries)} queries, results={len(results)} rows, filters={len(applied_filters)}")

    return ActiveQueryContext(
        current_table=table_name,
        current_sql=sql_queries[0] if sql_queries else "",
        applied_filters=applied_filters,
        grouping_columns=list(set(grouping_columns)),  # Unique
        order_by_columns=order_by_columns,
        result_sample=result_sample,
        result_row_count=len(results) if results else 0,
        last_execution_time=datetime.now().isoformat(),
        confidence_score=0.8
    )


# =============================================================================
# NODE FUNCTIONS
# =============================================================================

async def immediate_acknowledgment_node(state: ReportState) -> Dict[str, Any]:
    """
    Kullanıcıya hızlı geri bildirim ver.

    İşlem başladığını belirten mesaj gönderir.

    Phase 1: Session tracking ve conversation turn counter başlatır.
    Phase 4: Performance tracker başlatır.
    """
    logger.info("[REPORT] Sending immediate acknowledgment")

    # Phase 1: Initialize session tracking
    session_id = state.get("session_id")
    conversation_turn = state.get("conversation_turn", 0)

    # Increment turn counter
    new_turn = conversation_turn + 1

    logger.info(f"[REPORT] [SESSION] Turn {new_turn}")
    if session_id:
        logger.info(f"[REPORT] [SESSION] ID: {session_id}")

    return {
        "messages": [AIMessage(content="🔄 Sorgunuz işleniyor...")],
        "conversation_turn": new_turn
    }


def create_intent_classifier_node(llm: BaseChatModel, enable_fast_path: bool = True):
    """
    Intent classifier node factory.

    Args:
        llm: Language model for classification
        enable_fast_path: Enable fast-path pattern matching (Phase 1 optimization)

    Returns:
        Node function
    """
    # LLM classifier (daha doğru ama yavaş)
    llm_classifier = IntentClassifier(llm)

    # Simple classifier (hızlı fallback)
    simple_classifier = SimpleIntentClassifier()

    async def classify_intent_node(state: ReportState) -> Dict[str, Any]:
        """
        Kullanıcı mesajını sınıflandır.

        OPTIMIZATION (Phase 1): Fast-path pattern matching before LLM.
        Context varken HER ZAMAN LLM classifier kullanır (daha doğru analiz).
        Context yokken önce fast-path, sonra simple classifier, en son LLM.
        """
        user_message = get_last_user_message(state)
        if not user_message:
            return {"error": "No user message found"}

        logger.info(f"[REPORT] Classifying intent: {user_message[:50]}...")

        user_lower = user_message.lower()
        active_context = state.get("active_query_context")
        has_context = active_context is not None

        # =====================================================================
        # PHASE 1 OPTIMIZATION: FAST-PATH PATTERN MATCHING
        # =====================================================================
        if enable_fast_path and not has_context:
            # FAST PATH 1: Explicit rollback
            rollback_keywords = ["geri al", "iptal", "undo", "vazgeç", "önceki"]
            if any(kw in user_lower for kw in rollback_keywords):
                logger.info("[REPORT] ⚡ Fast path: ROLLBACK")
                return {
                    "user_query": user_message,  # FIXED: Add user_query
                    "_intent_type": "rollback",
                    "_confidence": 1.0,
                    "_extracted_entities": {},
                    "_intent_reasoning": "Fast path: Explicit rollback pattern"
                }

            # FAST PATH 2: Explicit visualization
            viz_keywords = ["grafik yap", "chart", "bar chart", "pasta grafik", "çubuk grafik", "grafik çiz", "grafiğe dönüştür"]
            if any(kw in user_lower for kw in viz_keywords):
                logger.info("[REPORT] ⚡ Fast path: VISUALIZE")
                return {
                    "user_query": user_message,  # FIXED: Add user_query
                    "_intent_type": "visualize",
                    "_confidence": 0.95,
                    "_extracted_entities": {},
                    "_intent_reasoning": "Fast path: Explicit visualization request"
                }

            # FAST PATH 3: Simple new query (basic keywords, no complex context)
            simple_query_keywords = ["göster", "listele", "rapor", "getir", "bul", "say"]
            if any(kw in user_lower for kw in simple_query_keywords):
                # Check if query is truly simple (short, no complex phrases)
                if len(user_message.split()) <= 8:
                    logger.info("[REPORT] ⚡ Fast path: Simple NEW_QUERY")
                    return {
                        "user_query": user_message,  # FIXED: Add user_query
                        "_intent_type": "new_query",
                        "_confidence": 0.85,
                        "_extracted_entities": {},
                        "_intent_reasoning": "Fast path: Simple query pattern",
                        # Note: query_type will be None, extract_query_node will handle it
                        "query_type": None,
                        "query_type_confidence": 0.0,
                        "reference_context": {},
                        "_needs_clarification": False
                    }

            logger.debug("[REPORT] No fast-path match, proceeding to classifier")

        # =====================================================================
        # STANDARD CLASSIFICATION PATH
        # =====================================================================

        # Context varsa HER ZAMAN LLM classifier kullan
        # Çünkü "burdaki", "peki bunun" gibi ifadeleri anlamak için context gerekli
        if has_context:
            logger.info("[REPORT] Context exists, using LLM classifier for accurate analysis")
            messages = state.get("messages", [])
            try:
                classification = await llm_classifier.classify(
                    user_message, messages, active_context
                )
                logger.info(f"[REPORT] LLM classification: {classification.intent_type.value} (confidence: {classification.confidence})")
            except Exception as e:
                logger.error(f"[REPORT] LLM classifier error: {e}, falling back to simple")
                classification = simple_classifier.classify(user_message, has_context)
        else:
            # Context yoksa önce simple classifier dene (hızlı)
            simple_result = simple_classifier.classify(user_message, has_context)

            # Confidence yeterli değilse LLM classifier kullan
            if simple_result.confidence < 0.6:
                logger.info("[REPORT] Low confidence, using LLM classifier")
                messages = state.get("messages", [])
                try:
                    classification = await llm_classifier.classify(
                        user_message, messages, active_context
                    )
                except Exception as e:
                    logger.error(f"[REPORT] LLM classifier error: {e}")
                    classification = simple_result
            else:
                classification = simple_result
                logger.info(f"[REPORT] Simple classifier sufficient: {classification.intent_type}")

        # =========================================================================
        # ENHANCED HITL - AMBIGUITY DETECTION (v2.0)
        # =========================================================================

        # Check if enhanced HITL is enabled
        enable_enhanced_hitl = HITL_CONFIG.get("enable_enhanced_hitl", True)

        if enable_enhanced_hitl:
            # Store classification in state for ambiguity detection
            temp_state = {
                **state,
                "user_query": user_message,
                "_intent_type": classification.intent_type.value,
                "_confidence": classification.confidence,
                "_extracted_entities": classification.extracted_entities
            }

            # Detect ambiguities using enhanced system
            intent_detector = create_intent_detector()
            ambiguity = await intent_detector.detect_ambiguity(temp_state, stage="intent")

            # ⚠️ CRITICAL: Check if HITL should be triggered
            max_clarifications = HITL_CONFIG.get("max_clarification_count", 3)
            if ambiguity and should_trigger_hitl(temp_state, ambiguity, max_clarifications):
                logger.warning(
                    f"[REPORT] ⚠️ AMBIGUITY DETECTED: {ambiguity.ambiguity_type} - "
                    f"TRIGGERING HITL (This is critical for understanding user intent!)"
                )

                # Track ambiguity metrics
                _track_ambiguity_metric(ambiguity.ambiguity_type, "detected")

                # Build user-friendly question
                question_builder = HITLQuestionBuilder()
                question_template = question_builder.build_question(ambiguity)

                # Increment clarification count
                new_clarification_count = temp_state.get("clarification_count", 0) + 1

                # Create HITL request
                pending_question = question_template.to_pending_question()

                logger.info(f"[REPORT] HITL question prepared: {pending_question['question'][:100]}...")

                return {
                    "pending_question": pending_question,
                    "waiting_for_user_input": True,
                    "ambiguity_context": ambiguity,
                    "clarification_count": new_clarification_count,
                    "user_query": user_message,
                    "_intent_type": classification.intent_type.value,
                    "_confidence": classification.confidence,
                    "_extracted_entities": classification.extracted_entities
                }

            # Check for auto-resolvable ambiguities
            if ambiguity and ambiguity.auto_resolvable:
                logger.info(f"[REPORT] Auto-resolving {ambiguity.ambiguity_type}")
                temp_state = apply_auto_resolution(temp_state, ambiguity)
                _track_ambiguity_metric(ambiguity.ambiguity_type, "auto_resolved")

        # LEGACY: Fall back to old HITL system if no enhanced ambiguity detected
        if classification.requires_clarification and (not enable_enhanced_hitl or not ambiguity):
            logger.info("[REPORT] Legacy clarification required, preparing HITL")

            # Soru oluştur
            if classification.clarification_question:
                question = classification.clarification_question
                options = classification.clarification_options or ["Evet", "Hayır"]
            else:
                # Default question based on intent type
                question = "Ne yapmak istediğinizi tam anlayamadım."
                options = ["Yeni rapor oluştur", "Mevcut raporu değiştir"]

            clarification = create_clarification_request(
                question=question,
                options=options,
                context=f"Tespit edilen niyet: {classification.intent_type.value}"
            )
            # FIXED: Add user_query to legacy clarification return
            clarification["user_query"] = user_message
            return clarification

        # =====================================================================
        # PHASE 2: CONTEXT-AWARE QUERY ANALYSIS (LLM-DRIVEN)
        # =====================================================================
        conversation_history = state.get("conversation_history", [])
        last_query_results = state.get("last_query_results")

        # Default query analysis
        query_analysis = {
            "query_type": None,
            "confidence": 0.0,
            "is_followup": False,
            "needs_clarification": False,
            "reference_context": {}
        }

        logger.info("[PHASE2] Running context-aware query analysis...")
        try:
            query_analysis = await _analyze_query_with_context(
                user_message=user_message,
                active_context=active_context,
                conversation_history=conversation_history,
                last_query_results=last_query_results,
                llm=llm
            )
            logger.info(f"[PHASE2] [QUERY_ANALYSIS] Result: type={query_analysis.get('query_type')}, "
                       f"conf={query_analysis.get('confidence', 0):.2f}, "
                       f"followup={query_analysis.get('is_followup', False)}")
        except Exception as e:
            logger.error(f"[PHASE2] [QUERY_ANALYSIS] Failed: {e}", exc_info=True)
            # Continue with default values (backward compatible)

        should_ask_user = query_analysis.get("needs_clarification", False)

        # Classification bilgisini state'e kaydet
        return {
            "user_query": user_message,
            "_intent_type": classification.intent_type.value,
            "_confidence": classification.confidence,
            "_extracted_entities": classification.extracted_entities,
            # Phase 2: NEW fields
            "query_type": query_analysis.get("query_type"),
            "query_type_confidence": query_analysis.get("confidence", 0.0),
            "reference_context": query_analysis.get("reference_context", {}),
            "_needs_clarification": should_ask_user,
        }

    return classify_intent_node


async def update_conversation_history_node(state: ReportState) -> Dict[str, Any]:
    """
    Update conversation history after SQL execution (Phase 5).

    CRITICAL: Must be called after every successful query!

    Updates:
    - conversation_history: Appends new query-result pair
    - last_query_results: Updates for next follow-up query

    Memory Management:
    - Max 5 queries in history
    - Max 10 results per query

    Args:
        state: ReportState

    Returns:
        Updated state with conversation_history and last_query_results
    """
    from datetime import datetime

    text2sql_output = state.get("text2sql_output")
    if not text2sql_output or text2sql_output.get("error"):
        logger.info("[HISTORY] No valid results, skipping history update")
        return {}  # Don't save failed queries

    user_query = get_last_user_message(state)
    query_type = state.get("query_type")
    results = text2sql_output.get("results", [])

    # Get or init history
    conversation_history = state.get("conversation_history") or []

    # Add new entry with enhanced entity tracking
    # CRITICAL: Extract entities from results for ALL query types
    extracted_entities_from_state = state.get("extracted_entities", {})

    # If no extracted_entities in state (e.g., ranking queries), extract from results
    if not extracted_entities_from_state.get("entities") and results and len(results) > 0:
        first_key = list(results[0].keys())[0]
        entities_from_results = [r.get(first_key) for r in results[:10] if r.get(first_key)]

        logger.info(f"[HISTORY] Extracting entities from results: {entities_from_results[:3]}")

        extracted_entities_dict = {
            "entities": entities_from_results,
            "entity_column": first_key,
            "entity_type": first_key,
            "source": "results"
        }
    else:
        # Use extracted_entities from state (for comparison queries)
        extracted_entities_dict = {
            "entities": extracted_entities_from_state.get("entities", []),
            "entity_column": extracted_entities_from_state.get("entity_column"),
            "entity_type": extracted_entities_from_state.get("entity_column") or (list(results[0].keys())[0] if results else None),
            "source": "validation_node"
        }

    new_entry = {
        "query": user_query,
        "query_type": query_type,
        "results": results[:10],  # Max 10 results to save memory
        "timestamp": datetime.now().isoformat(),
        # ENHANCED: Entity bilgilerini de sakla (HER query type için!)
        "extracted_entities": extracted_entities_dict,
        # NEW: Kullanılan filtreleri sakla
        "filters": state.get("active_query_context", {}).get("applied_filters", []),
        "grouping": state.get("active_query_context", {}).get("grouping_columns", [])
    }
    conversation_history.append(new_entry)

    # Keep only last 5 queries
    if len(conversation_history) > 5:
        conversation_history = conversation_history[-5:]

    # Update last_query_results for next follow-up
    last_query_results = None
    if results and len(results) > 0:
        first_key = list(results[0].keys())[0]
        entities = [r.get(first_key) for r in results]

        # Detect entity type (simple heuristic)
        entity_type = "unknown"
        if "branch" in first_key.lower() or "sube" in first_key.lower():
            entity_type = "branch"
        elif "product" in first_key.lower() or "urun" in first_key.lower():
            entity_type = "product"
        elif "category" in first_key.lower() or "kategori" in first_key.lower():
            entity_type = "category"
        elif "city" in first_key.lower() or "sehir" in first_key.lower():
            entity_type = "city"
        elif "customer" in first_key.lower() or "musteri" in first_key.lower():
            entity_type = "customer"

        last_query_results = {
            "entities": entities,
            "entity_type": entity_type,
            "filters": {f"{first_key}__in": entities},  # SQL WHERE için
        }

    logger.info(f"[PHASE5] [HISTORY] Updated: {len(conversation_history)} entries, "
               f"last_results={'present' if last_query_results else 'none'}")

    if last_query_results:
        entities_preview = last_query_results['entities'][:3]
        logger.info(f"[PHASE5] [HISTORY] Last query results: {len(last_query_results['entities'])} "
                   f"{last_query_results['entity_type']} entities "
                   f"(preview: {entities_preview})")

    return {
        "conversation_history": conversation_history,
        "last_query_results": last_query_results,
    }


def create_validate_entities_node(llm: BaseChatModel):
    """
    Factory function to create validate_entities_node with LLM.

    Args:
        llm: Language model for entity extraction

    Returns:
        Node function
    """
    async def validate_entities_node(state: ReportState) -> Dict[str, Any]:
        """
        Validate extracted entities and time period for queries.

        Checks:
        - Comparison/time_series_comparison needs minimum 2 entities
        - Time_series/time_series_comparison needs time period
        - If entities or period missing, trigger clarification

        Returns:
            State update with entity validation results
        """
        query_type = state.get("query_type")

        # Only validate for queries that need entities or period
        # NOTE: Ranking queries don't need validation (entities extracted from results)
        if query_type not in ["comparison", "time_series_comparison", "time_series"]:
            logger.info(f"[ENTITY_VALIDATE] Query type {query_type} doesn't require validation")
            return {"_entity_validation_done": True}  # Mark as done to prevent routing loop

        user_message = get_last_user_message(state)
        conversation_history = state.get("conversation_history", [])
        needs_clarification = False
        clarification_type = None  # "entity" or "period"

        # =================================================================
        # ENTITY VALIDATION (for comparison queries)
        # =================================================================
        # CRITICAL: Only comparison and time_series_comparison need entity extraction
        # Ranking queries get entities from RESULTS, not from user query
        entity_result = {}
        if query_type in ["comparison", "time_series_comparison"]:
            # Use SMART entity validation pipeline
            from .entity_validator import smart_entity_validation_pipeline

            logger.info(f"[ENTITY_VALIDATE] 🚀 Starting SMART entity validation pipeline for {query_type}")

            entity_result = await smart_entity_validation_pipeline(
                user_query=user_message,
                query_type=query_type,
                conversation_history=conversation_history,
                llm=llm
            )

            entities = entity_result.get("entities", [])
            entity_confidence = entity_result.get("confidence", 0.0)
            validation_passed = entity_result.get("validation_passed", False)
            strategy_used = entity_result.get("strategy_used", "unknown")

            logger.info(f"[ENTITY_VALIDATE] Pipeline result:")
            logger.info(f"  - Entities: {entities}")
            logger.info(f"  - Confidence: {entity_confidence:.2f}")
            logger.info(f"  - Strategy: {strategy_used}")
            logger.info(f"  - Validation: {'PASSED' if validation_passed else 'FAILED'}")

            # Use pipeline's validation result
            if validation_passed:
                # Pipeline validated, no clarification needed
                needs_clarification = False
                logger.info(f"[ENTITY_VALIDATE] ✓ Smart validation PASSED")
            else:
                # Pipeline failed validation, needs clarification
                needs_clarification = True
                clarification_type = "entity"
                validation_error = entity_result.get("validation_error", "unknown")
                logger.warning(f"[ENTITY_VALIDATE] ✗ Smart validation FAILED: {validation_error}")

        # Ranking queries don't need entity extraction from user query
        # Entities are extracted from SQL results in update_conversation_history_node
        elif query_type == "ranking":
            logger.info(f"[ENTITY_VALIDATE] Ranking query - entities will be extracted from results")

        # =================================================================
        # TIME PERIOD VALIDATION (for time_series queries)
        # =================================================================
        period_result = {}
        if query_type in ["time_series", "time_series_comparison"]:
            # Check if period exists in parsed_intent or state
            parsed_intent = state.get("parsed_intent", {})

            # Look for period in various places
            period = None
            period_source = None

            # Check in parsed_intent steps
            if parsed_intent.get("steps"):
                for step in parsed_intent["steps"]:
                    step_filters = step.get("filters", [])
                    for f in step_filters:
                        if "DocumentDate" in f.get("field_hint", "") and "DATEADD" in str(f.get("value_hint", "")):
                            period = f.get("value_hint", "")
                            period_source = "parsed_intent"
                            break
                    if period:
                        break

            # Check in active_query_context
            if not period:
                active_context = state.get("active_query_context", {})
                filters = active_context.get("applied_filters", [])
                for f in filters:
                    if f.get("column") == "DocumentDate" and "DATEADD" in str(f.get("value", "")):
                        period = f.get("value", "")
                        period_source = "active_context"
                        break

            # Check user query for time indicators
            if not period:
                time_indicators = ["son", "geçen", "bu", "şu", "bu yıl", "geçen ay", "son 6 ay", "son hafta"]
                if any(indicator in user_message.lower() for indicator in time_indicators):
                    period = "inferred_from_query"
                    period_source = "user_query"

            logger.info(f"[PERIOD_VALIDATE] Period: {period}, source: {period_source}")

            # If no period found, need clarification
            if not period:
                logger.warning(f"[PERIOD_VALIDATE] Time series query but no period found!")
                needs_clarification = True
                clarification_type = "period"

            period_result = {
                "period": period,
                "period_source": period_source,
                "has_period": bool(period)
            }

        # Extract SQL hints for SQL generation (if expansion query)
        sql_hints = entity_result.get("sql_hints", {})

        return {
            "extracted_entities": entity_result,
            "extracted_period": period_result,
            "entity_sql_hints": sql_hints,  # NEW: SQL generation hints
            "_needs_clarification": needs_clarification,
            "_clarification_type": clarification_type,
            "_entity_validation_done": True
        }

    return validate_entities_node


async def ask_user_for_clarification_node(state: ReportState) -> Dict[str, Any]:
    """
    Ask user when query type is ambiguous (Phase 3).

    CRITICAL: LLM-driven ambiguity detection triggers this node.

    Triggered when:
    - Query type confidence < 0.6
    - Reference detected but unclear context
    - Ambiguous intent

    Examples:
        "bunları göster" → Which analysis type?
        "şubeleri analiz et" → Ranking? Comparison? Aggregation?

    Returns:
        Updated state with user's selected query_type
    """
    from langgraph.types import interrupt

    user_message = get_last_user_message(state)
    query_type = state.get("query_type", "unknown")
    confidence = state.get("query_type_confidence", 0.0)
    reference_context = state.get("reference_context", {})

    logger.info(f"[ASK_USER] Query type ambiguous: '{user_message[:50]}...', "
               f"type={query_type}, confidence={confidence:.2f}")

    # Check clarification type
    clarification_type = state.get("_clarification_type")
    entity_validation = state.get("_entity_validation_done", False)

    # =================================================================
    # PERIOD CLARIFICATION (for time_series queries)
    # =================================================================
    if entity_validation and clarification_type == "period":
        extracted_period = state.get("extracted_period", {})

        message = f"""🤔 **Sorgunuz:** "{user_message}"

⏰ Hangi zaman aralığını analiz etmek istiyorsunuz?

**Öneriler:**
- Son 7 gün
- Son 1 ay
- Son 3 ay
- Son 6 ay
- Son 1 yıl
- Bu ay
- Bu yıl

Lütfen zaman aralığını girin (örn: "son 6 ay", "bu yıl"):
"""

        from langgraph.types import interrupt
        user_input = interrupt({
            "message": message,
            "type": "period_clarification",
            "query_type": query_type
        })

        logger.info(f"[ASK_USER] User clarified period: {user_input}")

        # Parse period input
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

        # If not in mapping, try to extract manually
        if not period_value:
            period_value = user_input  # Use as-is, will be processed by SQL architect

        return {
            "extracted_period": {
                "period": period_value,
                "period_source": "user_clarification",
                "has_period": True
            },
            "_needs_clarification": False,
            "_clarification_type": None
        }

    # =================================================================
    # ENTITY CLARIFICATION (for comparison queries)
    # =================================================================
    extracted_entities = state.get("extracted_entities", {})

    if entity_validation and clarification_type == "entity" and extracted_entities.get("needs_clarification"):
        entities = extracted_entities.get("entities", [])
        entity_column = extracted_entities.get("entity_column", "Entity")

        # Ask user which entities to compare
        message = f"""🤔 **Sorgunuz:** "{user_message}"

Hangi {entity_column}'leri karşılaştırmak istiyorsunuz?

{'📌 Tespit edilen: ' + ', '.join(entities) if entities else ''}

Lütfen karşılaştırmak istediğiniz en az 2 {entity_column} girin (virgülle ayırın):
"""

        from langgraph.types import interrupt
        user_input = interrupt({
            "message": message,
            "type": "entity_clarification",
            "current_entities": entities,
            "entity_column": entity_column
        })

        # Parse user input (comma separated)
        clarified_entities = [e.strip() for e in user_input.split(",")]

        logger.info(f"[ASK_USER] User clarified entities: {clarified_entities}")

        return {
            "extracted_entities": {
                "entities": clarified_entities,
                "entity_column": entity_column,
                "confidence": 1.0,
                "needs_clarification": False,
                "entity_source": "user_clarification"
            },
            "_needs_clarification": False
        }

    # Options for user selection
    options = {
        "ranking": "Sıralama (Top-N)",
        "comparison": "Karşılaştırma (A vs B)",
        "time_series": "Zaman Serisi",
        "aggregation": "Gruplama/Toplam",
        "distribution": "Dağılım",
    }

    # Add context info if follow-up query
    context_info = ""
    if reference_context.get("is_followup"):
        prev_entities = reference_context.get("previous_entities", [])
        if prev_entities:
            context_info = f"\n\n📌 Önceki sonuçlar: {', '.join(str(e) for e in prev_entities[:3])}"

    message = f"""🤔 **Sorgunuz:** "{user_message}"

Sorgu türü belirsiz (güven: {confidence:.0%}). Hangi analiz türünü istiyorsunuz?{context_info}

**Seçenekler:**
"""
    for key, label in options.items():
        message += f"\n- **{key}**: {label}"

    # Interrupt to ask user
    user_choice = interrupt({
        "message": message,
        "type": "query_type_clarification",
        "options": list(options.keys()),
    })

    logger.info(f"[ASK_USER] User selected: {user_choice}")

    return {
        "query_type": user_choice,
        "query_type_confidence": 1.0,  # User confirmation → high confidence
        "_needs_clarification": False,
    }


async def process_user_clarification_node(state: ReportState) -> Dict[str, Any]:
    """
    Kullanıcı yanıtını işle (Enhanced HITL v2.0).

    interrupt_before sonrası resume edildiğinde çalışır.

    Processing flow:
    1. Check for ambiguity_context (Enhanced system)
    2. Route to type-specific processor
    3. Fallback to legacy system if no ambiguity_context

    Supports:
    - Context ambiguity (keep/clear filters)
    - Prompt scope (query clarification)
    - Intent ambiguity (what user wants)
    - Column ambiguity (which column)
    - Value ambiguity (which value)
    """
    user_response = state.get("user_clarification")
    pending_question = state.get("pending_question")

    if not user_response:
        logger.warning("[REPORT] No user clarification found")
        return {}

    logger.info(f"[REPORT] Processing clarification: {user_response}")

    # =========================================================================
    # ENHANCED HITL - Ambiguity-aware processing
    # =========================================================================
    ambiguity_ctx = state.get("ambiguity_context")

    if ambiguity_ctx:
        logger.info(f"[REPORT] Enhanced processing for {ambiguity_ctx.ambiguity_type}")
        return await _process_enhanced_clarification(state, ambiguity_ctx, user_response)

    # =========================================================================
    # LEGACY HITL - Backward compatibility
    # =========================================================================
    logger.info("[REPORT] Using legacy clarification processing")
    return _process_legacy_clarification(state, user_response, pending_question)

    # Yanıta göre intent'i belirle
    response_lower = user_response.lower()
    result = {
        "pending_question": None,
        "waiting_for_user_input": False,
        "user_clarification": None
    }

    # Pending question context'ine göre analiz et
    question_context = pending_question.get("context", "") if pending_question else ""
    question_text = pending_question.get("question", "") if pending_question else ""

    # =========================================================================
    # USER PREFERENCES CLARIFICATION
    # =========================================================================
    if "tercihleri" in question_text or "tercihleriniz" in question_text:
        logger.info(f"[REPORT] User preference received: {user_response}")
        # Tercihi _user_preference olarak kaydet
        result["_user_preference"] = user_response
        result["_preference_type"] = "date_range" if "gün" in user_response or "ay" in user_response or "yıl" in user_response else "general"
        result["_intent_type"] = "new_query"  # Tercih alındı, sorguya devam et
        logger.info(f"[REPORT] User preference set: {user_response}")
        return result

    # =========================================================================
    # "DID YOU MEAN" CLARIFICATION
    # =========================================================================
    if "demek istediniz" in question_text or "kullanılsın mı" in question_text:
        logger.info(f"[REPORT] 'Did you mean' clarification received: {user_response}")

        if "evet" in response_lower or "doğru" in response_lower:
            # Kullanıcı öneriyi kabul etti
            # Pending question'dan suggested field'ı çıkar
            if pending_question:
                question_parts = pending_question.get("question", "").split("'")
                if len(question_parts) >= 4:
                    suggested_value = question_parts[3]  # "... 'suggested_value' ..."
                    result["_selected_value"] = suggested_value
                    result["_clarification_type"] = "value"
                    result["_intent_type"] = "retry_with_clarification"
                    logger.info(f"[REPORT] User accepted suggestion: {suggested_value}")
        else:
            # Kullanıcı öneriyi reddetti, tam olarak yazdığını kullan
            result["_use_exact_input"] = True
            result["_intent_type"] = "new_query"
            logger.info("[REPORT] User rejected suggestion, using exact input")

        return result

    # =========================================================================
    # METADATA AMBIGUITY - Column/Value Clarification
    # =========================================================================
    # "için hangi kolonu" veya "için hangi değeri" ifadeleri metadata ambiguity sorusu
    if "için hangi kolonu" in question_text or "birden fazla kolon" in question_context:
        # Column ambiguity clarification
        logger.info(f"[REPORT] Column ambiguity clarification received: {user_response}")
        result["_selected_column"] = user_response
        result["_clarification_type"] = "column"
        # Text2SQL'i tekrar çalıştırmak için intent set et
        result["_intent_type"] = "retry_with_clarification"
        return result

    if "için hangi değeri" in question_text or "için birden fazla eşleşme" in question_context:
        # Value ambiguity clarification
        logger.info(f"[REPORT] Value ambiguity clarification received: {user_response}")
        result["_selected_value"] = user_response
        result["_clarification_type"] = "value"
        # Text2SQL'i tekrar çalıştırmak için intent set et
        result["_intent_type"] = "retry_with_clarification"
        return result

    # =========================================================================
    # REGULAR CLARIFICATIONS (Empty Result, Modification Type, etc.)
    # =========================================================================

    # Empty result recovery sorusu için
    if "boş sonuç" in question_context.lower() or "veri bulunamadı" in question_context.lower():
        if "geri" in response_lower or "önceki" in response_lower:
            result["_intent_type"] = IntentType.ROLLBACK.value
            logger.info("[REPORT] User chose rollback after empty result")
        elif "genişlet" in response_lower or "filtre" in response_lower:
            result["_intent_type"] = IntentType.MODIFY_FILTER.value
            result["_modification_action"] = "expand_filter"
            logger.info("[REPORT] User chose to expand filter")
        else:
            result["_intent_type"] = IntentType.NEW_QUERY.value
            logger.info("[REPORT] User chose new query")
        return result

    # Tablo belirsizliği için
    if "hangi tablo" in question_context.lower():
        # Kullanıcının seçtiği tablo adını kaydet
        result["_selected_table"] = user_response
        result["_intent_type"] = IntentType.NEW_QUERY.value
        logger.info(f"[REPORT] User selected table: {user_response}")
        return result

    # Filtre değeri belirsizliği için
    if "hangi değer" in question_context.lower() or "için birden fazla" in question_context.lower():
        result["_selected_filter_value"] = user_response
        result["_intent_type"] = IntentType.MODIFY_FILTER.value
        logger.info(f"[REPORT] User selected filter value: {user_response}")
        return result

    # Modifikasyon tipi belirsizliği için
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

    # Genel fallback
    if "yeni" in response_lower or "oluştur" in response_lower:
        result["_intent_type"] = IntentType.NEW_QUERY.value
    elif "değiştir" in response_lower or "ekle" in response_lower:
        result["_intent_type"] = IntentType.MODIFY_FILTER.value
    elif "geri" in response_lower or "önceki" in response_lower:
        result["_intent_type"] = IntentType.ROLLBACK.value
    else:
        result["_intent_type"] = IntentType.NEW_QUERY.value

    return result


async def extract_query_node(state: ReportState) -> Dict[str, Any]:
    """
    Kullanıcı sorgusunu çıkar ve doğrula.

    Messages'dan son HumanMessage'ı alır ve state'e kaydeder.
    Merged Text2SQL nodes için user_query alanını doldurur.

    Phase 1: Conversation context oluşturur ve Text2SQL nodes'a geçer.
    """
    user_query = get_last_user_message(state)

    if not user_query:
        logger.error("[REPORT] No user message found")
        return {"error": "No user message found"}

    logger.info(f"[REPORT] Extracted query: {user_query[:100]}...")

    # =========================================================================
    # PHASE 4: CONTEXT INJECTION FOR FOLLOW-UP QUERIES (CRITICAL!)
    # =========================================================================
    reference_context = state.get("reference_context", {})
    last_query_results = state.get("last_query_results")
    is_followup = reference_context.get("is_followup", False)

    logger.info(f"[PHASE4] Context injection check: is_followup={is_followup}, "
               f"has_last_results={last_query_results is not None}")

    # SQL context for injection
    sql_context_hint = ""

    if is_followup and last_query_results:
        prev_entities = last_query_results.get("entities", [])
        entity_type = last_query_results.get("entity_type", "entity")

        if prev_entities:
            # SECURITY: Escape for SQL injection prevention
            # Single quotes → doubled single quotes (SQL standard)
            entities_escaped = [str(e).replace("'", "''") for e in prev_entities[:20]]  # Max 20
            entities_str = "', '".join(entities_escaped)

            # Build natural language context hint for Text2SQL
            sql_context_hint = f"""
ÖNEMLI CONTEXT (Kullanıcı önceki sonuçlara referans veriyor):
Önceki sorgu sonuçları ({entity_type}): {', '.join(str(e) for e in prev_entities[:5])}
Toplam {len(prev_entities)} entity.

SQL oluştururken WHERE clause ekle:
WHERE {entity_type} IN ('{entities_str}')
VEYA
WHERE {entity_type}_name IN ('{entities_str}')

NOT: Entity isimlerini yukarıdaki listeden kullan, başka entity ekleme!
"""
            # Enrich user query with context
            enriched_query = f"{user_query}\n\n{sql_context_hint}"

            logger.info(f"[REPORT] [PHASE4] Context injection: {len(prev_entities)} {entity_type} entities")
            logger.info(f"[REPORT] [PHASE4] SQL context hint: {sql_context_hint[:200]}...")

            user_query = enriched_query

    # Phase 1: Build conversation context for Text2SQL nodes
    active_context = state.get("active_query_context")
    conversation_context = _build_conversation_context(active_context, state)

    if conversation_context:
        logger.info(f"[REPORT] [CONTEXT] Built conversation context: {list(conversation_context.keys())}")

    # Phase 1: Determine execution mode
    current_intent = state.get("_intent_type", "new_query")
    last_intent = state.get("last_intent")
    confidence = state.get("_confidence", 0.0)

    execution_mode = _determine_execution_mode(
        intent_type=current_intent,
        active_context=active_context,
        last_intent=last_intent,
        confidence=confidence
    )

    logger.info(f"[REPORT] [EXTRACT_QUERY] Execution mode: {execution_mode}")

    # CRITICAL: For contextual_full mode, enrich user query with context filters
    if execution_mode == "contextual_full" and active_context:
        enriched_query = _enrich_query_with_context(user_query, active_context)
        logger.info(f"[REPORT] [CONTEXTUAL_FULL] Enriched query: {enriched_query[:150]}...")

        # ⚠️ CRITICAL: Preserve context filters if explicitly requested
        preserve_context = state.get("_preserve_context", False)
        context_filters_to_keep = state.get("_context_filters_to_keep", [])
        context_grouping_to_keep = state.get("_context_grouping_to_keep", [])

        result = {
            "user_query": enriched_query,  # Enriched query for full SQL generation
            "conversation_context": conversation_context,
            "last_intent": current_intent,
            "_execution_mode": "full",  # Use full pipeline but with enriched query
            "_reuse_table": True,       # Reuse existing table for performance
            "_skip_table_creation": True
        }

        # If user explicitly chose to keep context, preserve it for merging later
        if preserve_context and (context_filters_to_keep or context_grouping_to_keep):
            logger.info(
                f"[REPORT] [CONTEXTUAL_FULL] ⚠️ PRESERVING CONTEXT: "
                f"{len(context_filters_to_keep)} filters, {len(context_grouping_to_keep)} grouping"
            )
            result["_preserved_filters"] = context_filters_to_keep
            result["_preserved_grouping"] = context_grouping_to_keep
            result["_merge_preserved_context"] = True

        return result

    return {
        "user_query": user_query,
        "conversation_context": conversation_context,
        "last_intent": current_intent,
        "_execution_mode": execution_mode,
        "_sql_context_injected": bool(sql_context_hint),  # Phase 4: tracking
    }


def _enrich_query_with_context(
    user_query: str,
    active_context: Dict[str, Any]
) -> str:
    """
    Enrich user query with context filters (for contextual_full mode).

    Converts context filters to natural language and prepends to user query.
    This allows full SQL generation with preserved context.

    Example:
        user_query = "Toplam tutarı göster"
        context = {"applied_filters": [{"column": "BranchCityName", "value": "Ankara"}]}
        →
        enriched = "Ankara için toplam tutarı göster"

    Args:
        user_query: Original user query
        active_context: Active query context with filters

    Returns:
        Enriched query with context filters
    """
    filters = active_context.get("applied_filters", [])

    if not filters:
        return user_query

    # Build filter phrase from context
    filter_phrases = []

    for f in filters:
        column = f.get("column", "")
        value = f.get("value", "")
        operator = f.get("operator", "=")

        if not column or not value:
            continue

        # Convert to natural language
        if operator == "=":
            filter_phrases.append(str(value))
        elif operator == "IN":
            if isinstance(value, list):
                filter_phrases.append(", ".join(str(v) for v in value))
            else:
                filter_phrases.append(str(value))
        elif operator == ">":
            filter_phrases.append(f"{value}'den büyük")
        elif operator == "<":
            filter_phrases.append(f"{value}'den küçük")
        else:
            filter_phrases.append(f"{column} {operator} {value}")

    if not filter_phrases:
        return user_query

    # Combine filters
    filter_text = ", ".join(filter_phrases)

    # Prepend to user query
    enriched_query = f"{filter_text} için {user_query}"

    logger.info(f"[CONTEXT_ENRICH] Original: '{user_query}' → Enriched: '{enriched_query}'")

    return enriched_query


def _build_conversation_context(
    active_context: Optional[Dict[str, Any]],
    state: ReportState
) -> Optional[Dict[str, Any]]:
    """
    Build conversation context for Text2SQL nodes (Phase 1).

    Context includes:
    - Previous table
    - Previous filters
    - Previous columns
    - Result statistics
    - Execution metadata

    Returns:
        Conversation context dict or None if no active context
    """
    if not active_context:
        return None

    context = {
        "has_previous_query": True,
        "previous_table": active_context.get("current_table", ""),
        "previous_sql": active_context.get("current_sql", ""),
        "previous_filters": active_context.get("applied_filters", []),
        "previous_grouping": active_context.get("grouping_columns", []),
        "previous_ordering": active_context.get("order_by_columns", []),
        "result_row_count": active_context.get("result_row_count", 0),
        "last_execution_time": active_context.get("last_execution_time", ""),
        "confidence_score": active_context.get("confidence_score", 0.0)
    }

    # Add query history summary
    query_history = state.get("query_history", [])
    if query_history:
        context["query_count"] = len(query_history)
        context["last_version"] = query_history[-1].get("version", 0) if query_history else 0

    return context


# =============================================================================
# PHASE 2: DELTA SQL EXECUTION
# =============================================================================

async def delta_sql_modifier_node(state: ReportState) -> Dict[str, Any]:
    """
    Delta SQL modifier - Modify existing SQL instead of rebuilding (Phase 4).

    Handles incremental changes with semantic column name resolution:
    - Filter additions/removals/modifications
    - Column additions/removals (with semantic name resolution)
    - Aggregation changes
    - Ordering changes
    - Limit changes

    Phase 4 improvements:
    - Uses AdvancedDeltaParser for LLM-based parsing
    - Uses SQLModifier with ValueResolver for semantic column name resolution
    - Prevents "Invalid column name" errors by resolving semantic names to DB columns

    This node BYPASSES:
    - create_table (reuses existing)
    - sql_architect
    - retrieve_business_rules
    - metadata_enrichment
    - value_resolver
    - sql_query_builder

    Goes directly to sql_executor, saving ~60-70% latency.

    Returns:
        Updated state with modified SQL queries
    """
    logger.info("=" * 80)
    logger.info("[DELTA_SQL] Starting delta SQL modification (Phase 4 optimization)")

    try:
        # Get active context and user query
        active_context = state.get("active_query_context")
        user_query = state.get("user_query", "")
        intent_type = state.get("_intent_type", "")

        if not active_context:
            logger.error("[DELTA_SQL] No active context - cannot perform delta update")
            return {"error": "Delta execution requires previous query context"}

        base_sql = active_context.get("current_sql", "")
        if not base_sql:
            logger.error("[DELTA_SQL] No base SQL found in active context")
            return {"error": "No previous SQL found for delta update"}

        logger.info(f"[DELTA_SQL] Base SQL: {base_sql[:200]}...")
        logger.info(f"[DELTA_SQL] Intent: {intent_type}")
        logger.info(f"[DELTA_SQL] User query: {user_query[:100]}...")

        # Get or initialize value resolver for column name resolution
        value_resolver = state.get("value_resolver")
        if not value_resolver:
            logger.warning("[DELTA_SQL] No value_resolver in state - initializing new instance")
            try:
                from src.graphs.generic_text2sql.value_resolver_service import ValueResolverService
                from src.config import get_config
                import os

                config = get_config()
                db_connection_string = os.getenv("DATABASE_URL") or config.get("database", {}).get("connection_string")
                session_id = state.get("session_id", "default")
                table_name = active_context.get("current_table", "MasterReportDocumentTable")

                # Check if session-specific table exists
                if session_id and session_id != "default":
                    table_name_with_session = f"{table_name}_{session_id}"
                else:
                    table_name_with_session = table_name

                value_resolver = ValueResolverService(
                    db_connection_string=db_connection_string,
                    table_name=table_name_with_session
                )
                # Initialize semantic mappings
                value_resolver._init_column_semantic_mapping()
                logger.info(f"[DELTA_SQL] ✅ ValueResolver initialized for table: {table_name_with_session}")
            except Exception as e:
                logger.error(f"[DELTA_SQL] ❌ Failed to initialize value_resolver: {e}")
                value_resolver = None

        # Get column metadata for accurate column name resolution
        column_metadata = state.get("schema_metadata") or state.get("column_metadata")

        # CRITICAL: If no schema metadata in state, fetch from database
        if not column_metadata:
            logger.warning("[DELTA_SQL] No schema_metadata in state - fetching from database")
            try:
                from src.graphs.generic_text2sql.schema_discovery import get_schema_discovery_service
                import os

                db_connection_string = os.getenv("DATABASE_URL")
                table_name = active_context.get("current_table", "MasterReportDocumentTable")
                session_id = state.get("session_id", "default")

                # Check for session-specific table
                if session_id and session_id != "default":
                    table_name_with_session = f"{table_name}_{session_id}"
                else:
                    table_name_with_session = table_name

                # Fetch schema from database
                schema_service = await get_schema_discovery_service(db_connection_string)
                table_metadata = await schema_service.discover_table_schema(table_name_with_session)

                if table_metadata and table_metadata.columns:
                    # Convert to column metadata dict
                    column_metadata = {
                        col.column_name: {
                            "type": col.data_type,
                            "description": col.description or ""
                        }
                        for col in table_metadata.columns
                    }
                    logger.info(f"[DELTA_SQL] ✅ Fetched {len(column_metadata)} columns from database")
                else:
                    logger.error(f"[DELTA_SQL] ❌ Failed to fetch schema for table: {table_name_with_session}")

            except Exception as e:
                logger.error(f"[DELTA_SQL] ❌ Error fetching schema metadata: {e}")
                column_metadata = None

        if column_metadata:
            logger.info(f"[DELTA_SQL] Using {len(column_metadata)} columns for validation")
        else:
            logger.error("[DELTA_SQL] ❌ CRITICAL: No column metadata available - SQL may be invalid!")

        # Parse user intent for delta changes (with column metadata and value resolver)
        delta_changes = await _parse_delta_changes(
            user_query,
            intent_type,
            active_context,
            column_metadata,
            value_resolver
        )

        if not delta_changes:
            logger.warning("[DELTA_SQL] Could not parse delta changes, falling back to full execution")
            return {"_delta_fallback": True}

        # Apply delta modifications with value resolver
        modified_sql = _apply_sql_delta(base_sql, delta_changes, active_context, value_resolver)

        logger.info(f"[DELTA_SQL] Modified SQL: {modified_sql[:200]}...")
        logger.info(f"[DELTA_SQL] ✓ Delta modification completed")
        logger.info("=" * 80)

        # Return with flags for downstream nodes
        return {
            "sql_queries": [modified_sql],
            "_skip_table_creation": True,      # Reuse existing table
            "_reuse_table": True,              # Signal to executor
            "_delta_execution": True,          # Track delta execution
            "_delta_changes": delta_changes    # Store for debugging
        }

    except Exception as e:
        logger.error(f"[DELTA_SQL] Error during delta modification: {e}", exc_info=True)
        logger.warning("[DELTA_SQL] Falling back to full execution")
        return {"_delta_fallback": True}


async def _parse_delta_changes(
    user_query: str,
    intent_type: str,
    active_context: Dict[str, Any],
    column_metadata: Optional[Dict[str, str]] = None,
    value_resolver = None
) -> Optional[Dict[str, Any]]:
    """
    Parse user query to extract delta changes (Phase 4: LLM-based with semantic resolution).

    Uses LLM to understand delta modifications and resolves semantic column names
    to actual database columns to prevent "Invalid column name" errors.

    Phase 4 improvements:
    - Uses AdvancedDeltaParser for structured parsing
    - Resolves semantic column names (e.g., "Tutar" → "RowAmount")
    - Better confidence scoring for fallback decisions

    Args:
        user_query: User's modification request
        intent_type: Intent type (modify_filter, modify_aggregation, etc.)
        active_context: Previous query context
        column_metadata: Available column names and descriptions
        value_resolver: ValueResolverService for semantic column name resolution

    Returns:
        Dict with delta changes or None if cannot parse
    """
    from langchain_openai import ChatOpenAI

    logger.info("[DELTA_SQL] ⚡ Phase 4: Using LLM-based delta parsing with semantic resolution")

    # Phase 4: Use AdvancedDeltaParser for structured parsing
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    parser = AdvancedDeltaParser(llm)

    try:
        # Use AdvancedDeltaParser to parse delta changes WITH SCHEMA METADATA
        delta_changes = await parser.parse_advanced_delta(
            user_query=user_query,
            active_context=active_context,
            intent_type=intent_type,
            schema_metadata=column_metadata  # CRITICAL: Pass table schema!
        )

        if not delta_changes or delta_changes.get("modification_type") == "unknown":
            logger.warning("[DELTA_SQL] AdvancedDeltaParser returned unknown modification type")
            return await _fallback_pattern_matching(user_query, intent_type)

        confidence = delta_changes.get("confidence", 0.0)
        logger.info(f"[DELTA_SQL] ⚡ Phase 4 parsing confidence: {confidence:.2f}")

        # Resolve semantic column names using ValueResolver
        if value_resolver:
            delta_changes = _resolve_delta_column_names(delta_changes, value_resolver)

        # Validate confidence threshold
        if confidence < 0.6:
            logger.warning(f"[DELTA_SQL] Low confidence ({confidence:.2f}), falling back")
            return None

        logger.info(f"[DELTA_SQL] ✓ LLM parsed: {len(delta_changes.get('filters_to_add', []))} filters, "
                   f"limit={delta_changes.get('limit_change')}")

        return delta_changes

    except Exception as e:
        logger.warning(f"[DELTA_SQL] LLM parsing failed: {e}, trying pattern matching fallback")

        # Fallback to Phase 2 pattern matching
        return _parse_delta_changes_pattern_matching(user_query, intent_type)


def _parse_delta_changes_pattern_matching(
    user_query: str,
    intent_type: str
) -> Optional[Dict[str, Any]]:
    """
    Fallback pattern matching parser (Phase 2 method).

    Returns:
        Dict with delta changes or None
    """
    user_query_lower = user_query.lower()
    delta_changes = {
        "type": intent_type,
        "filters_to_add": [],
        "filters_to_remove": [],
        "columns_to_add": [],
        "columns_to_remove": [],
        "ordering_change": None,
        "limit_change": None,
        "parsing_method": "pattern_matching"
    }

    # Filter additions
    if any(keyword in user_query_lower for keyword in ["sadece", "için", "ile", "where"]):
        logger.info("[DELTA_SQL] Pattern: Detected filter addition")
        delta_changes["filters_to_add"].append({
            "raw_query": user_query,
            "extraction_method": "pattern_matching"
        })

    # Limit changes
    if any(keyword in user_query_lower for keyword in ["top", "ilk", "en çok", "limit"]):
        import re
        match = re.search(r'\b(\d+)\b', user_query)
        if match:
            limit = int(match.group(1))
            delta_changes["limit_change"] = limit
            logger.info(f"[DELTA_SQL] Pattern: Detected limit change: {limit}")

    # Ordering changes - Parse basic ordering patterns
    if any(keyword in user_query_lower for keyword in ["sırala", "büyükten", "küçükten", "order"]):
        # Try to extract direction from user query
        direction = "DESC" if any(k in user_query_lower for k in ["büyükten", "desc"]) else "ASC"

        # For pattern matching, we can't reliably extract column name
        # Mark it for LLM parsing or use default
        delta_changes["ordering_change"] = {
            "column": None,  # Will be resolved by LLM or context
            "direction": direction,
            "_needs_parsing": True
        }
        logger.info(f"[DELTA_SQL] Pattern: Detected ordering change (direction: {direction})")

    # If no changes detected, return None
    if not any([
        delta_changes["filters_to_add"],
        delta_changes["filters_to_remove"],
        delta_changes["columns_to_add"],
        delta_changes["columns_to_remove"],
        delta_changes["ordering_change"],
        delta_changes["limit_change"]
    ]):
        return None

    return delta_changes


def _apply_sql_delta(
    base_sql: str,
    delta_changes: Dict[str, Any],
    active_context: Dict[str, Any],
    value_resolver = None
) -> str:
    """
    Apply delta changes to base SQL (Phase 4: With SQLModifier and semantic resolution).

    Phase 4 improvements:
    - Uses SQLModifier for robust SQL manipulation
    - Resolves semantic column names to prevent "Invalid column name" errors
    - Handles complex aggregation and column operations

    Args:
        base_sql: Original SQL query
        delta_changes: Parsed delta changes from AdvancedDeltaParser
        active_context: Active query context
        value_resolver: ValueResolverService for column name resolution

    Returns:
        Modified SQL query
    """
    import re
    modified_sql = base_sql
    parsing_method = delta_changes.get("parsing_method", "unknown")

    logger.info(f"[DELTA_SQL] Applying delta changes (method: {parsing_method})")

    # Initialize SQLModifier with value_resolver
    sql_modifier = SQLModifier(value_resolver)

    # Phase 4: Apply column additions using SQLModifier
    columns_to_add = delta_changes.get("columns_to_add", [])
    if columns_to_add:
        logger.info(f"[DELTA_SQL] ⚡ Phase 4: Adding {len(columns_to_add)} columns")
        modified_sql = sql_modifier.add_columns(modified_sql, columns_to_add)

    # Phase 4: Apply column removals using SQLModifier
    columns_to_remove = delta_changes.get("columns_to_remove", [])
    if columns_to_remove:
        logger.info(f"[DELTA_SQL] ⚡ Phase 4: Removing {len(columns_to_remove)} columns")
        modified_sql = sql_modifier.remove_columns(modified_sql, columns_to_remove)

    # Phase 4: Apply aggregation changes using SQLModifier
    aggregation_changes = delta_changes.get("aggregation_changes", {})
    if aggregation_changes:
        logger.info("[DELTA_SQL] ⚡ Phase 4: Applying aggregation changes")
        modified_sql = sql_modifier.modify_aggregations(modified_sql, aggregation_changes)

    # Phase 4: Apply structured filter additions (from LLM)
    filters_to_add = delta_changes.get("filters_to_add", [])
    if filters_to_add and isinstance(filters_to_add[0], dict) and "column" in filters_to_add[0]:
        # Phase 3: Structured filters from LLM
        logger.info(f"[DELTA_SQL] ⚡ Phase 3: Applying {len(filters_to_add)} structured filters")

        for filter_def in filters_to_add:
            column = filter_def.get("column")
            operator = filter_def.get("operator", "=")
            value = filter_def.get("value")

            if not column or not value:
                continue

            filter_clause = f"{column} {operator} '{value}'"

            # Add WHERE clause
            if "WHERE" in modified_sql.upper():
                # Find WHERE position and add AND
                where_match = re.search(r'\bWHERE\b', modified_sql, re.IGNORECASE)
                if where_match:
                    pos = where_match.end()
                    modified_sql = modified_sql[:pos] + f" {filter_clause} AND " + modified_sql[pos:]
            else:
                # Add WHERE clause before ORDER BY or at end
                if "ORDER BY" in modified_sql.upper():
                    modified_sql = re.sub(
                        r'\bORDER BY\b',
                        f"WHERE {filter_clause} ORDER BY",
                        modified_sql,
                        count=1,
                        flags=re.IGNORECASE
                    )
                else:
                    modified_sql += f" WHERE {filter_clause}"

            logger.info(f"[DELTA_SQL] ✓ Added filter: {filter_clause}")

    elif filters_to_add:
        # Fallback: Phase 2 pattern matching for filters
        logger.info("[DELTA_SQL] Using Phase 2 pattern matching for filters")
        raw_query = filters_to_add[0].get("raw_query", "")
        cities = ["istanbul", "ankara", "izmir", "bursa", "antalya"]
        for city in cities:
            if city in raw_query.lower():
                if "WHERE" in modified_sql.upper():
                    modified_sql = modified_sql.replace(" WHERE ", f" WHERE Sehir = '{city.title()}' AND ")
                else:
                    if "ORDER BY" in modified_sql.upper():
                        modified_sql = modified_sql.replace(" ORDER BY", f" WHERE Sehir = '{city.title()}' ORDER BY")
                    else:
                        modified_sql += f" WHERE Sehir = '{city.title()}'"
                logger.info(f"[DELTA_SQL] Added filter: Sehir = '{city.title()}'")
                break

    # Apply limit changes
    limit_change = delta_changes.get("limit_change")
    if limit_change:
        if "TOP" in modified_sql.upper():
            modified_sql = re.sub(r'TOP\s+\d+', f'TOP {limit_change}', modified_sql, flags=re.IGNORECASE)
            logger.info(f"[DELTA_SQL] ✓ Updated limit: TOP {limit_change}")
        else:
            modified_sql = modified_sql.replace("SELECT", f"SELECT TOP {limit_change}", 1)
            logger.info(f"[DELTA_SQL] ✓ Added limit: TOP {limit_change}")

    # Phase 3: Apply ordering changes (structured from LLM)
    ordering_change = delta_changes.get("ordering_change")
    if ordering_change and isinstance(ordering_change, dict):
        column = ordering_change.get("column")
        direction = ordering_change.get("direction", "ASC")

        if column:
            order_clause = f"ORDER BY {column} {direction}"

            if "ORDER BY" in modified_sql.upper():
                # Remove existing ORDER BY clause completely (supports multiple columns)
                # Pattern matches: ORDER BY ... (everything until semicolon or end)
                modified_sql = re.sub(
                    r'\s*ORDER\s+BY\s+[^;]+',
                    '',
                    modified_sql,
                    flags=re.IGNORECASE
                ).rstrip()

            # Add new ORDER BY at end
            modified_sql += f" {order_clause}"

            logger.info(f"[DELTA_SQL] ✓ Applied ordering: {order_clause}")

    return modified_sql


def _resolve_delta_column_names(delta_changes: Dict[str, Any], value_resolver) -> Dict[str, Any]:
    """
    Resolve semantic column names in delta changes to actual database columns.

    This prevents "Invalid column name" errors by ensuring all column references
    use actual database column names instead of semantic/natural language names.

    Args:
        delta_changes: Delta changes from parser
        value_resolver: ValueResolverService instance

    Returns:
        Delta changes with resolved column names
    """
    logger.info("[DELTA_SQL] Resolving semantic column names...")

    # Resolve filters_to_add
    filters_to_add = delta_changes.get("filters_to_add", [])
    for filter_def in filters_to_add:
        if "column" in filter_def:
            original = filter_def["column"]
            resolved = value_resolver.resolve_column_name(original)
            if resolved and resolved != original:
                logger.info(f"[DELTA_SQL]   Filter column: '{original}' → '{resolved}'")
                filter_def["column"] = resolved

    # Resolve columns_to_add
    columns_to_add = delta_changes.get("columns_to_add", [])
    for col_def in columns_to_add:
        if "name" in col_def:
            original = col_def["name"]
            resolved = value_resolver.resolve_column_name(original)
            if resolved and resolved != original:
                logger.info(f"[DELTA_SQL]   Add column: '{original}' → '{resolved}'")
                col_def["name"] = resolved

    # Resolve columns_to_remove
    columns_to_remove = delta_changes.get("columns_to_remove", [])
    resolved_removals = []
    for col_name in columns_to_remove:
        resolved = value_resolver.resolve_column_name(col_name)
        if resolved and resolved != col_name:
            logger.info(f"[DELTA_SQL]   Remove column: '{col_name}' → '{resolved}'")
            resolved_removals.append(resolved)
        else:
            resolved_removals.append(col_name)
    delta_changes["columns_to_remove"] = resolved_removals

    # Resolve aggregation_changes new_grouping
    agg_changes = delta_changes.get("aggregation_changes", {})
    if agg_changes and "new_grouping" in agg_changes:
        new_grouping = agg_changes["new_grouping"]
        resolved_grouping = []
        for col_name in new_grouping:
            resolved = value_resolver.resolve_column_name(col_name)
            if resolved and resolved != col_name:
                logger.info(f"[DELTA_SQL]   GROUP BY column: '{col_name}' → '{resolved}'")
                resolved_grouping.append(resolved)
            else:
                resolved_grouping.append(col_name)
        agg_changes["new_grouping"] = resolved_grouping

    # Resolve ordering_change column
    ordering_change = delta_changes.get("limit_offset_changes", {}).get("ordering_change")
    if isinstance(ordering_change, dict) and "column" in ordering_change:
        original = ordering_change["column"]
        resolved = value_resolver.resolve_column_name(original)
        if resolved and resolved != original:
            logger.info(f"[DELTA_SQL]   ORDER BY column: '{original}' → '{resolved}'")
            ordering_change["column"] = resolved

    logger.info("[DELTA_SQL] ✅ Column name resolution completed")
    return delta_changes


async def _fallback_pattern_matching(user_query: str, intent_type: str) -> Optional[Dict[str, Any]]:
    """
    Fallback to simple pattern matching when LLM parsing fails.

    This is a simplified version that handles basic delta operations
    without semantic column resolution.

    Args:
        user_query: User's modification request
        intent_type: Intent type

    Returns:
        Basic delta changes or None
    """
    logger.info("[DELTA_SQL] Using fallback pattern matching")

    user_query_lower = user_query.lower()

    delta_changes = {
        "type": intent_type,
        "filters_to_add": [],
        "filters_to_remove": [],
        "columns_to_add": [],
        "columns_to_remove": [],
        "ordering_change": None,
        "limit_change": None,
        "parsing_method": "pattern_matching"
    }

    # Filter additions
    if any(keyword in user_query_lower for keyword in ["sadece", "için", "ile", "where"]):
        logger.info("[DELTA_SQL] Pattern: Detected filter addition")
        delta_changes["filters_to_add"].append({
            "raw_query": user_query,
            "extraction_method": "pattern_matching"
        })

    # Limit changes
    if any(keyword in user_query_lower for keyword in ["top", "ilk", "en çok", "limit"]):
        import re
        match = re.search(r'\b(\d+)\b', user_query)
        if match:
            limit = int(match.group(1))
            delta_changes["limit_change"] = limit
            logger.info(f"[DELTA_SQL] Pattern: Detected limit change: {limit}")

    # Ordering changes - Parse basic ordering patterns
    if any(keyword in user_query_lower for keyword in ["sırala", "büyükten", "küçükten", "order"]):
        # Try to extract direction from user query
        direction = "DESC" if any(k in user_query_lower for k in ["büyükten", "desc"]) else "ASC"

        # For pattern matching, we can't reliably extract column name
        # Mark it for LLM parsing or use default
        delta_changes["ordering_change"] = {
            "column": None,  # Will be resolved by LLM or context
            "direction": direction,
            "_needs_parsing": True
        }
        logger.info(f"[DELTA_SQL] Pattern: Detected ordering change (direction: {direction})")

    # If no changes detected, return None
    if not any([
        delta_changes["filters_to_add"],
        delta_changes["filters_to_remove"],
        delta_changes["columns_to_add"],
        delta_changes["columns_to_remove"],
        delta_changes["ordering_change"],
        delta_changes["limit_change"]
    ]):
        return None

    return delta_changes


async def check_results_node(state: ReportState) -> Dict[str, Any]:
    """
    Text2SQL sonuçlarını kontrol et.

    1. Önce resolution_metadata'daki belirsizlikleri kontrol et (column/value ambiguity)
    2. Belirsizlik varsa kullanıcıya HITL sorusu sor
    3. Yoksa boş sonuç kontrolü yap
    4. Her şey OK ise context güncelle

    Supports both merged mode (direct state fields) and backward compatibility (text2sql_output).
    """
    # Önceki node'dan gelen hatayı kontrol et
    prev_error = state.get("error")
    if prev_error:
        logger.warning(f"[REPORT] Previous error detected: {prev_error}")
        return {"error": prev_error}

    # For merged mode: check direct state fields
    # For backward compatibility: check text2sql_output
    text2sql_output = state.get("text2sql_output")
    results = state.get("results")
    resolution_metadata = state.get("resolution_metadata")

    # Determine which mode we're in
    if results is not None:
        # Merged mode: use direct state fields
        logger.info("[REPORT] Using merged mode (direct state fields)")
        data_results = results
        data_resolution_metadata = resolution_metadata
    elif text2sql_output:
        # Backward compatibility mode: use text2sql_output
        logger.info("[REPORT] Using backward compatibility mode (text2sql_output)")
        data_results = text2sql_output.get("results", [])
        data_resolution_metadata = text2sql_output.get("resolution_metadata")
    else:
        logger.error("[REPORT] No results found in state (neither merged nor text2sql_output)")
        return {"error": "Sorgu işlenemedi. Lütfen tekrar deneyin."}

    # =========================================================================
    # METADATA KONTROLÜ - Column/Value Belirsizliği
    # =========================================================================
    resolution_metadata = data_resolution_metadata

    if resolution_metadata:
        logger.info(f"[REPORT] Checking resolution_metadata for ambiguities...")

        # Column belirsizliği kontrolü
        ambiguous_fields = resolution_metadata.get("ambiguous_fields", [])
        if ambiguous_fields and len(ambiguous_fields) > 0:
            # İlk belirsiz field'ı al
            ambiguous_field = ambiguous_fields[0]
            field_hint = ambiguous_field.get("field_hint", "Bilinmeyen alan")
            candidates = ambiguous_field.get("candidates", [])

            if candidates and len(candidates) > 1:
                logger.info(f"[REPORT] Column ambiguity detected: {field_hint} has {len(candidates)} candidates")

                # Sadece kolon isimlerini al (top 5)
                column_options = [c.get("column_name", str(c)) for c in candidates[:5]]

                return HITLQuestions.column_ambiguity(
                    field_hint=field_hint,
                    possible_columns=column_options,
                    context=f"'{field_hint}' için birden fazla kolon bulundu."
                )

        # Value belirsizliği kontrolü
        fuzzy_matches = resolution_metadata.get("fuzzy_matches", [])
        if fuzzy_matches and len(fuzzy_matches) > 0:
            # İlk fuzzy match'i al
            fuzzy_match = fuzzy_matches[0]
            field_hint = fuzzy_match.get("field_hint", "Bilinmeyen alan")
            value_hint = fuzzy_match.get("value_hint", "")
            matched_values = fuzzy_match.get("matched_values", [])

            if matched_values and len(matched_values) > 1:
                logger.info(f"[REPORT] Value ambiguity detected: '{value_hint}' has {len(matched_values)} matches")

                # =====================================================================
                # "DID YOU MEAN" PATTERN - Tek bir güçlü eşleşme varsa
                # =====================================================================
                best_match = matched_values[0] if matched_values else None
                similarity_score = fuzzy_match.get("similarity_score", 0)

                # Eğer tek bir güçlü eşleşme varsa (similarity > 0.7), "Did you mean" sor
                if best_match and len(matched_values) == 1:
                    logger.info(f"[REPORT] Single fuzzy match: '{value_hint}' → '{best_match}', asking 'did you mean'")
                    return HITLQuestions.did_you_mean_field(
                        user_input=value_hint,
                        suggested_field=str(best_match),
                        field_type="value"
                    )

                # Birden fazla eşleşme → Tam liste sun
                # Top 5 değeri al
                value_options = [str(v) for v in matched_values[:5]]

                return HITLQuestions.filter_value_ambiguity(
                    column=field_hint,
                    value_hint=value_hint,
                    possible_values=value_options
                )

    # =========================================================================
    # RESULTS KONTROLÜ
    # =========================================================================
    results = data_results
    logger.info(f"[REPORT] Checking results: {len(results) if results else 0} rows")

    if not results or len(results) == 0:
        logger.info("[REPORT] Empty results, preparing recovery question")

        # HITL: Boş sonuç recovery sorusu
        active_context = state.get("active_query_context")
        if active_context:
            return HITLQuestions.empty_result_recovery(
                active_context.get("current_sql", "")
            )

        return {"no_records_message": "Sorguya uygun kayıt bulunamadı."}

    # Sonuç varsa context'i güncelle
    active_context = state.get("active_query_context")
    # For merged mode, create a compatible dict for update_active_context
    if text2sql_output:
        updated_context = update_active_context(active_context, text2sql_output)
    else:
        # Merged mode: construct text2sql_output-like dict
        text2sql_output_dict = {
            "results": data_results,
            "sql_queries": state.get("sql_queries", []),
            "parsed_intent": state.get("parsed_intent")
        }
        updated_context = update_active_context(active_context, text2sql_output_dict)

    # ⚠️ CRITICAL: Merge preserved context filters if user chose to keep them
    merge_preserved = state.get("_merge_preserved_context", False)
    if merge_preserved:
        preserved_filters = state.get("_preserved_filters", [])
        preserved_grouping = state.get("_preserved_grouping", [])

        if preserved_filters or preserved_grouping:
            logger.warning(
                f"[REPORT] ⚠️ MERGING PRESERVED CONTEXT: "
                f"{len(preserved_filters)} filters, {len(preserved_grouping)} grouping"
            )

            # Merge preserved filters with new context
            existing_filters = updated_context.get("applied_filters", [])

            # Add preserved filters that don't already exist
            merged_filters = list(existing_filters)
            for pf in preserved_filters:
                # Check if filter already exists
                if not any(
                    ef.get("column") == pf.get("column") and
                    ef.get("value") == pf.get("value")
                    for ef in existing_filters
                ):
                    merged_filters.append(pf)
                    logger.info(
                        f"[REPORT] ✅ Merged preserved filter: "
                        f"{pf.get('column')} {pf.get('operator', '=')} {pf.get('value')}"
                    )

            updated_context["applied_filters"] = merged_filters

            # Merge preserved grouping
            if preserved_grouping:
                existing_grouping = updated_context.get("grouping_columns", [])
                merged_grouping = list(set(existing_grouping + preserved_grouping))
                updated_context["grouping_columns"] = merged_grouping

            logger.info(
                f"[REPORT] ✓ Context merge completed: "
                f"Total filters={len(merged_filters)}, Total grouping={len(merged_grouping)}"
            )

    # Checkpoint oluştur
    user_message = get_last_user_message(state)
    query_history = state.get("query_history", [])
    new_checkpoint = create_checkpoint(
        context=updated_context,
        user_message=user_message or "",
        version=len(query_history) + 1
    )

    return {
        "active_query_context": updated_context,
        "query_history": [new_checkpoint],
        "clarification_count": 0,  # ✅ Reset after successful query
        # Clear temporary flags
        "_merge_preserved_context": None,
        "_preserved_filters": None,
        "_preserved_grouping": None,
        "_preserve_context": None,
        "_context_filters_to_keep": None,
        "_context_grouping_to_keep": None
    }


def create_text2sql_node(text2sql_graph):
    """
    Text2SQL node factory.

    Context-aware: Eğer aktif context varsa ve intent modify_* ise,
    mevcut SQL'i modifiye edecek şekilde context injection yapar.

    Args:
        text2sql_graph: Compiled text2sql graph

    Returns:
        Node function
    """
    from langchain_core.runnables import RunnableConfig

    async def text2sql_node(state: ReportState, config: RunnableConfig = None) -> Dict[str, Any]:
        """
        Text2SQL graph'ı çağır with runtime config and context injection.

        Metadata clarification'ları da handle eder:
        - _selected_column: Kullanıcının seçtiği kolon
        - _selected_value: Kullanıcının seçtiği değer
        """
        user_query = get_last_user_message(state)

        if not user_query:
            return {"error": "No user query found", "text2sql_output": None}

        logger.info("[REPORT] Invoking text2sql graph...")

        try:
            # Context bilgisini al
            active_context = state.get("active_query_context")
            intent_type = state.get("_intent_type", "new_query")
            extracted_entities = state.get("_extracted_entities", {})

            # Metadata clarification'ları al
            selected_column = state.get("_selected_column")
            selected_value = state.get("_selected_value")
            clarification_type = state.get("_clarification_type")

            # User preference'ı al
            user_preference = state.get("_user_preference")
            preference_type = state.get("_preference_type")

            # Delta-SQL için query enhancement
            enhanced_query = user_query

            # =========================================================================
            # USER PREFERENCE INJECTION
            # =========================================================================
            if user_preference and preference_type:
                logger.info(f"[REPORT] User preference detected: {user_preference} (type: {preference_type})")

                # Tarih aralığı tercihi
                if preference_type == "date_range":
                    date_filter_hint = ""
                    if "7 gün" in user_preference:
                        date_filter_hint = "Son 7 günlük veri (DATEADD kullan)"
                    elif "30 gün" in user_preference:
                        date_filter_hint = "Son 30 günlük veri (DATEADD kullan)"
                    elif "bu ay" in user_preference.lower():
                        date_filter_hint = "Bu ayki veriler (MONTH ve YEAR filtresi)"
                    elif "bu yıl" in user_preference.lower():
                        date_filter_hint = "Bu yılki veriler (YEAR filtresi)"
                    elif "tüm" in user_preference.lower():
                        date_filter_hint = "Tüm veriler (tarih filtresi yok)"

                    if date_filter_hint:
                        enhanced_query = f"""{user_query}

KULLANICI TERCİHİ: {date_filter_hint}"""

                # Konum tercihi
                elif "şehir" in user_preference.lower() or "istanbul" in user_preference.lower() or "ankara" in user_preference.lower():
                    city = None
                    if "istanbul" in user_preference.lower():
                        city = "İstanbul"
                    elif "ankara" in user_preference.lower():
                        city = "Ankara"
                    elif "izmir" in user_preference.lower():
                        city = "İzmir"

                    if city:
                        enhanced_query = f"""{user_query}

KULLANICI TERCİHİ: Sadece {city} şehri için (BranchCityName veya CustomerCityName = '{city}')"""

                logger.info(f"[REPORT] Query enhanced with user preference")


            # =========================================================================
            # METADATA CLARIFICATION INJECTION
            # =========================================================================
            if clarification_type == "column" and selected_column:
                logger.info(f"[REPORT] Column clarification detected: using column '{selected_column}'")
                # Sorguya column clarification hint'i ekle
                enhanced_query = f"""{user_query}

ÖNEMLİ NOT: Kullanıcı belirsiz alan için '{selected_column}' kolonunu seçti. Bu kolonu kullan."""

            elif clarification_type == "value" and selected_value:
                logger.info(f"[REPORT] Value clarification detected: using value '{selected_value}'")
                # Sorguya value clarification hint'i ekle
                enhanced_query = f"""{user_query}

ÖNEMLİ NOT: Kullanıcı filtre değeri olarak '{selected_value}' seçti. Bu değeri kullan."""

            # =========================================================================
            # CONTEXT INJECTION (Modification intents)
            # =========================================================================

            # Eğer modify_* intent ise ve context varsa, sorguyu zenginleştir
            if active_context and intent_type in ["modify_filter", "modify_aggregation", "modify_columns", "modify_order"]:
                logger.info(f"[REPORT] Detected modification intent: {intent_type}")
                logger.info(f"[REPORT] Active context exists: table={active_context.get('current_table')}, filters={len(active_context.get('applied_filters', []))}, rows={active_context.get('result_row_count', 0)}")

                # Context bilgisini prompt'a ekle
                context_hint = _build_modification_context_hint(
                    active_context,
                    intent_type,
                    extracted_entities,
                    user_query
                )
                enhanced_query = context_hint

                logger.info(f"[REPORT] Enhanced query for modification (first 300 chars): {enhanced_query[:300]}...")
            else:
                # Context yok veya new_query intent
                if active_context:
                    logger.info(f"[REPORT] Active context exists but intent is {intent_type}, treating as new query")
                else:
                    logger.info(f"[REPORT] No active context, processing as new query")

            text2sql_input = {
                "user_query": enhanced_query,
                "parsed_intent": None,
                "enriched_metadata": None,
                "resolved_steps": None,
                "resolution_metadata": None,
                "sql_queries": None,
                "results": None,
                "final_response": None,
                "error": None
            }

            # Context meta bilgisini ekle (debug ve gelecek kullanım için)
            if active_context:
                text2sql_input["_previous_context"] = active_context
                text2sql_input["_is_modification"] = intent_type.startswith("modify_")

            # Pass runtime config to text2sql graph
            logger.debug(f"[REPORT] Passing config to text2sql: {config is not None}")
            logger.info(f"[REPORT] Text2SQL input query (first 300 chars): {enhanced_query[:300]}...")

            try:
                result = await text2sql_graph.ainvoke(text2sql_input, config)
            except Exception as invoke_error:
                logger.error(f"[REPORT] Text2SQL invoke failed: {invoke_error}", exc_info=True)
                return {
                    "error": f"Text2SQL invoke error: {invoke_error}",
                    "text2sql_output": None
                }

            # Result kontrolü
            if result is None:
                logger.error("[REPORT] Text2SQL returned None")
                return {
                    "error": "Text2SQL returned None",
                    "text2sql_output": None
                }

            # Error kontrolü
            if result.get("error"):
                logger.warning(f"[REPORT] Text2SQL returned with error: {result.get('error')}")

            # Results kontrolü - None olabilir
            results = result.get("results")
            result_count = len(results) if results else 0
            logger.info(f"[REPORT] Text2SQL completed: {result_count} rows")

            return {
                "text2sql_output": result,
                "error": result.get("error")
            }

        except Exception as e:
            logger.error(f"[REPORT] Text2SQL error: {e}", exc_info=True)
            return {"error": f"Text2SQL error: {e}", "text2sql_output": None}

    return text2sql_node


def _build_modification_context_hint(
    active_context: ActiveQueryContext,
    intent_type: str,
    extracted_entities: Dict[str, Any],
    user_query: str
) -> str:
    """
    Modification intent için context-aware sorgu oluştur.

    Mevcut SQL'i ve filtreleri açıklayarak, kullanıcının modifikasyon
    isteğini daha iyi anlaşılır hale getirir.

    Args:
        active_context: Mevcut sorgu context'i
        intent_type: Intent türü (modify_filter, modify_aggregation, vb.)
        extracted_entities: Intent'ten çıkarılan entity'ler
        user_query: Kullanıcının orijinal mesajı

    Returns:
        Zenginleştirilmiş sorgu string'i
    """
    # Mevcut filtreleri text'e çevir
    current_filters = active_context.get("applied_filters", [])
    filter_descriptions = []
    for f in current_filters:
        col = f.get("column", "")
        val = f.get("value", "")
        op = f.get("operator", "=")
        filter_descriptions.append(f"{col} {op} '{val}'")

    filters_text = ", ".join(filter_descriptions) if filter_descriptions else "filtre yok"

    # Gruplama bilgisi
    grouping = active_context.get("grouping_columns", [])
    grouping_text = ", ".join(grouping) if grouping else "gruplama yok"

    # Result sample bilgisini text'e çevir
    result_sample = active_context.get("result_sample", [])
    result_text = ""
    if result_sample:
        sample_lines = []
        for row in result_sample[:3]:  # İlk 3 satır
            sample_lines.append(str(row))
        result_text = "\n".join(sample_lines)

    # Modification type'a göre hint oluştur
    if intent_type == "modify_filter":
        # Filter ekleme/çıkarma/genişletme
        filter_action = extracted_entities.get("filter_action", "add")
        filter_column = extracted_entities.get("filter_column", "")
        filter_value = extracted_entities.get("filter_value", "")
        uses_context_ref = extracted_entities.get("uses_context_reference", False)

        if filter_action == "expand" or uses_context_ref:
            # Context-referencing sorgu: "burdaki ürünlerin", "bu kategorinin" vb.
            # Önceki sorgunun sonucunu kullanarak yeni sorgu oluştur
            hint = f"""ÖNCEKİ SORGU SONUCU (REFERANS):
Tablo: {active_context.get('current_table', 'MasterReportDocumentTable')}
Önceki SQL: {active_context.get('current_sql', '')[:500]}
Önceki Filtreler: {filters_text}
Önceki Gruplama: {grouping_text}
Sonuç Sayısı: {active_context.get('result_row_count', 0)} satır
Örnek Sonuç:
{result_text}

KULLANICI İSTEĞİ: {user_query}

GÖREV: Kullanıcı ÖNCEKİ SORGUNUN SONUCUNU REFERANS ALIYOR.
Örneğin: "burdaki ürünlerin satış oranlarını ver" = Önceki sorguda bulunan kategori/filtre ile ürün detaylarını getir.

ADIMLAR:
1. Önceki sorgunun sonucundaki değerleri (örn: CategoryName = 'DURUMLER') filtre olarak kullan
2. Kullanıcının istediği yeni bilgiyi (ürünler, satış oranları vb.) getir
3. Gerekirse GROUP BY ekle

ÖNEMLİ: Bu bir BAĞIMLI SORGU olabilir. Önceki sonucu WHERE clause'da kullan."""

        elif filter_action == "add":
            hint = f"""MEVCUT SORGU BAĞLAMI:
Tablo: {active_context.get('current_table', 'MasterReportDocumentTable')}
Mevcut Filtreler: {filters_text}
Mevcut Gruplama: {grouping_text}
Son Sonuç: {active_context.get('result_row_count', 0)} satır

KULLANICI İSTEĞİ: {user_query}

GÖREV: Yukarıdaki mevcut sorguya EK FİLTRE ekle. Mevcut filtreleri KORU, sadece yeni filtre ekle.
{f'Tespit Edilen Filtre: {filter_column} = {filter_value}' if filter_column else ''}"""

        elif filter_action == "remove":
            hint = f"""MEVCUT SORGU BAĞLAMI:
Tablo: {active_context.get('current_table', 'MasterReportDocumentTable')}
Mevcut Filtreler: {filters_text}
Mevcut Gruplama: {grouping_text}

KULLANICI İSTEĞİ: {user_query}

GÖREV: Mevcut filtrelerden birini ÇIKAR. Diğer filtreleri koru."""

        else:  # replace
            hint = f"""MEVCUT SORGU BAĞLAMI:
Tablo: {active_context.get('current_table', 'MasterReportDocumentTable')}
Mevcut Filtreler: {filters_text}

KULLANICI İSTEĞİ: {user_query}

GÖREV: Mevcut filtreyi DEĞİŞTİR."""

    elif intent_type == "modify_aggregation":
        hint = f"""MEVCUT SORGU BAĞLAMI:
Tablo: {active_context.get('current_table', 'MasterReportDocumentTable')}
Mevcut Filtreler: {filters_text}
Mevcut Gruplama: {grouping_text}

KULLANICI İSTEĞİ: {user_query}

GÖREV: Mevcut sorgunun GRUPLAMA/AGGREGATION'ını değiştir. Filtreleri KORU."""

    elif intent_type == "modify_order":
        hint = f"""MEVCUT SORGU BAĞLAMI:
Tablo: {active_context.get('current_table', 'MasterReportDocumentTable')}
Mevcut Filtreler: {filters_text}

KULLANICI İSTEĞİ: {user_query}

GÖREV: Mevcut sorgunun SIRALAMA'sını değiştir. Diğer her şeyi koru."""

    elif intent_type == "modify_columns":
        hint = f"""MEVCUT SORGU BAĞLAMI:
Tablo: {active_context.get('current_table', 'MasterReportDocumentTable')}
Mevcut Filtreler: {filters_text}

KULLANICI İSTEĞİ: {user_query}

GÖREV: Mevcut sorguya yeni KOLON ekle. Filtreleri ve diğer yapıyı koru."""

    else:
        # Fallback - orijinal sorguyu kullan
        hint = user_query

    return hint


def create_visualization_node(visualization_graph):
    """
    Visualization node factory.

    Karar logic'i artık report graph'ta (decide_visualization_node).
    Bu node sadece render işlemi yapar.

    Args:
        visualization_graph: Compiled visualization graph

    Returns:
        Node function
    """
    from langchain_core.runnables import RunnableConfig

    async def visualization_node(state: ReportState, config: RunnableConfig = None) -> Dict[str, Any]:
        """
        Visualization graph'ı çağır - sadece render işlemi.

        Karar logic'i decide_visualization_node'da yapıldı.

        IMPORTANT: Supports both "visualize_direct" and "normal" paths:
        - visualize_direct: Uses active_query_context
        - normal: Uses text2sql_output
        """
        text2sql_output = state.get("text2sql_output")
        active_context = state.get("active_query_context")
        viz_decision = state.get("_viz_decision")

        # Get data from appropriate source
        results = None
        sql_query = None
        metadata = {}

        if text2sql_output and not text2sql_output.get("error"):
            # Normal path - from text2sql
            results = text2sql_output.get("results", [])
            sql_query = text2sql_output.get("sql_query")
            metadata = text2sql_output.get("metadata", {})
            logger.debug("[REPORT] Using data from text2sql_output")
        elif active_context:
            # visualize_direct path - from active_query_context
            results = active_context.get("result_sample", [])
            sql_query = active_context.get("current_sql")
            metadata = {}
            logger.info("[REPORT] [VISUALIZE_DIRECT] Using data from active_query_context")
        else:
            logger.error("[REPORT] No data available for visualization")
            return {"error": "No data available for visualization", "visualization_output": None}

        if not results:
            return {"error": "No results to visualize", "visualization_output": None}

        # Auto-create viz_decision if missing (visualize_direct path)
        if not viz_decision:
            logger.info("[REPORT] [VISUALIZE_DIRECT] No viz_decision → creating default bar_chart decision")
            viz_decision = {
                "needs_graph": True,
                "output_type": "bar_chart",
                "reason": "Kullanıcı görselleştirme istedi"
            }

        # Check if graph is needed
        if not viz_decision.get("needs_graph"):
            logger.info(f"[REPORT] No graph needed: {viz_decision.get('reason')}")
            # Return formatted output without calling visualization graph
            output_type = viz_decision.get("output_type", "table")
            user_query = get_last_user_message(state) or ""

            formatted_output = {
                "summary": viz_decision.get("reason", "Sonuçlar hazır"),
                "output_type": output_type,
                "needs_graph": False,
                "data": results,
                "sql_query": sql_query,
                "metadata": metadata,
                "user_query": user_query  # Include user query for context
            }

            return {
                "visualization_output": formatted_output,
                "error": None
            }

        logger.info("[REPORT] Invoking visualization graph (render only)...")

        try:
            # Get user query for visualization context
            user_query = get_last_user_message(state) or ""

            # Prepare input with decision
            viz_input = {
                "results": results,
                "sql_query": sql_query,
                "metadata": metadata,
                "user_query": user_query,  # CRITICAL: Pass user intent to viz graph
                # Pass decision to visualization graph
                "_viz_decision": viz_decision
            }

            logger.debug(f"[REPORT] Passing user_query to viz graph: {user_query[:50]}...")

            # Pass runtime config to visualization graph
            result = await visualization_graph.ainvoke(viz_input, config)
            logger.info("[REPORT] Visualization completed")

            return {
                "visualization_output": result,
                "error": result.get("error")
            }

        except Exception as e:
            logger.error(f"[REPORT] Visualization error: {e}", exc_info=True)
            return {"error": f"Visualization error: {e}", "visualization_output": None}

    return visualization_node


async def rollback_node(state: ReportState) -> Dict[str, Any]:
    """
    Önceki checkpoint'e geri dön.

    Query history'den son checkpoint'i alır ve restore eder.
    """
    query_history = state.get("query_history", [])

    if len(query_history) < 2:
        logger.warning("[REPORT] Not enough history for rollback")
        return {
            "messages": [AIMessage(content="⚠️ Geri alınacak önceki sorgu yok.")]
        }

    # Son checkpoint'i çıkar (mevcut), bir öncekini al
    previous_checkpoint = query_history[-2]
    restored_context = previous_checkpoint["active_context"]

    logger.info(f"[REPORT] Rolling back to version {previous_checkpoint['version']}")

    return {
        "active_query_context": restored_context,
        "messages": [AIMessage(content=f"↩️ Önceki sorguya geri dönüldü (v{previous_checkpoint['version']})")]
    }


async def build_response_node(state: ReportState) -> Dict[str, Any]:
    """
    Final response oluştur.

    Basit:
    - data_visualization'dan gelirse HTML döndür
    - sql_execution'dan gelirse result döndür
    """
    # Hata kontrolü
    error = state.get("error")
    if error:
        return {"messages": [AIMessage(content=f"❌ Hata: {error}")]}

    no_records = state.get("no_records_message")
    if no_records:
        return {"messages": [AIMessage(content=f"ℹ️ {no_records}")]}

    # Data visualization'dan gelen HTML var mı?
    viz_output = state.get("visualization_output")
    if viz_output:
        plotly_html = viz_output.get("plotly_html_snippet")
        if plotly_html:
            # HTML döndür
            import base64
            html_full = f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0">{plotly_html}</body></html>'''
            html_b64 = base64.b64encode(html_full.encode('utf-8')).decode('ascii')
            iframe = f'<iframe src="data:text/html;charset=utf-8;base64,{html_b64}" width="100%" height="500" frameborder="0"></iframe>'
            return {"messages": [AIMessage(content=f"📈 Grafik:\n{iframe}")]}

    # SQL execution'dan gelen result var mı?
    results = state.get("results")
    if results:
        # Results'ı formatla ve döndür
        parts = [f"📊 **Sonuçlar** ({len(results)} kayıt):\n"]
        for i, row in enumerate(results[:50], 1):
            row_str = " | ".join([f"**{k}:** {v}" for k, v in row.items()])
            parts.append(f"{i}. {row_str}")

        if len(results) > 50:
            parts.append(f"\n... ve {len(results) - 50} kayıt daha")

        return {"messages": [AIMessage(content="\n".join(parts))]}

    # Hiçbir şey yoksa
    return {"messages": [AIMessage(content="⚠️ Sonuç bulunamadı")]}


# =============================================================================
# ROUTING FUNCTIONS (Conditional edges için)
# =============================================================================

# LLM Router için prompt template
ROUTING_DECISION_PROMPT = """Sen bir akıllı sorgu yönlendirme uzmanısın.

Görevin: Kullanıcının mesajını, konuşma geçmişini ve mevcut bağlamı analiz ederek
doğru işlem yolunu belirlemek.

## MEVCUT DURUM

Aktif Sorgu Bağlamı:
{context_info}

Intent Sınıflandırması:
- Tespit Edilen Intent: {intent_type}
- Güven Skoru: {confidence}
- Çıkarılan Bilgiler: {extracted_entities}

Kullanıcı Sorusu Bekliyor mu: {waiting_for_input}

## KONUŞMA GEÇMİŞİ (Son 5 mesaj)
{conversation_history}

## SON KULLANICI MESAJI
{user_message}

## ROUTING SEÇENEKLERİ

1. **ask_user** - Kullanıcıdan açıklama iste
   - Belirsiz ifadeler varsa ("bu", "şu", "o" ama neyi kastettiği belli değil)
   - Birden fazla olası yorum varsa
   - Kritik bir karar gerekiyorsa (örn: veri silme, büyük değişiklik)
   - confidence < 0.6 ise

2. **rollback** - Önceki sorguya geri dön
   - Kullanıcı açıkça geri almak istiyor ("geri al", "önceki", "iptal")
   - Hatalı bir işlem yapıldığını belirtiyor

3. **visualize_direct** - Mevcut veriyi grafiğe dönüştür (Text2SQL atla)
   - Kullanıcı "grafiğe dönüştür", "çubuk grafik yap" gibi ifadeler kullanıyor
   - Context'te mevcut sonuç var
   - Sadece visualization yapılacak, yeni SQL çalıştırılmayacak

4. **process_query** - Sorguyu işle
   - Yeni sorgu başlatılacak (new_query)
   - Mevcut sorgu modifiye edilecek (modify_*)
   - Confidence yeterli (>= 0.6)

## KARAR KRİTERLERİ

- Eğer waiting_for_input=true ise → ask_user
- Eğer kullanıcı açıkça "geri", "iptal", "önceki" diyorsa → rollback
- Eğer kullanıcı "grafiğe dönüştür", "çubuk grafik yap" diyorsa VE context varsa → visualize_direct
- Eğer intent belirsiz VEYA confidence düşük (<0.6) VEYA birden fazla anlam varsa → ask_user
- Aksi halde → process_query

## ÇIKTI FORMATI

Sadece aşağıdaki JSON formatında yanıt ver:
{{
    "route": "ask_user" | "rollback" | "process_query",
    "reason": "Kısa açıklama (1 cümle)",
    "clarification_needed": "Eğer ask_user ise, sorulacak soru (opsiyonel)"
}}"""


def create_route_after_intent(llm: BaseChatModel):
    """
    LLM tabanlı akıllı router factory.

    Tüm conversation history ve context'i analiz ederek
    en doğru routing kararını verir.

    Args:
        llm: Language model for routing decisions

    Returns:
        Async routing function
    """
    import json
    from langchain_core.prompts import ChatPromptTemplate

    prompt = ChatPromptTemplate.from_template(ROUTING_DECISION_PROMPT)

    async def smart_route_after_intent(state: ReportState) -> str:
        """
        LLM ile akıllı routing kararı.

        Tüm conversation history, active context ve intent bilgisini
        analiz ederek en uygun yönlendirmeyi yapar.

        Returns:
            Next node name: "ask_user", "rollback", or "process_query"
        """
        # HITL bekliyor mu? (öncelikli kontrol)
        waiting_for_input = state.get("waiting_for_user_input", False)
        if waiting_for_input:
            logger.info("[REPORT] Routing to ask_user (waiting for input flag set)")
            return "ask_user"

        # State bilgilerini topla
        intent_type = state.get("_intent_type", "new_query")
        confidence = state.get("_confidence", 0.0)
        extracted_entities = state.get("_extracted_entities", {})
        active_context = state.get("active_query_context")
        messages = state.get("messages", [])
        user_message = get_last_user_message(state) or ""

        # Hızlı yol: Rollback açıkça isteniyor
        if intent_type == "rollback" and confidence >= 0.7:
            logger.info("[REPORT] Fast path: routing to rollback")
            return "rollback"

        # Hızlı yol: Visualize (grafiğe dönüştür)
        if intent_type == "visualize" and confidence >= 0.85:
            logger.info("[REPORT] Fast path: routing to visualize_direct (skip text2sql)")
            return "visualize_direct"

        # Hızlı yol: Yüksek güvenli new_query
        if intent_type == "new_query" and confidence >= 0.85:
            logger.info("[REPORT] Fast path: routing to process_query (high confidence new_query)")
            return "process_query"

        # LLM ile detaylı analiz
        try:
            # Context bilgisini formatla
            if active_context:
                context_info = f"""VAR ✓
Tablo: {active_context.get('current_table', 'Bilinmiyor')}
Filtreler: {active_context.get('applied_filters', [])}
Gruplama: {active_context.get('grouping_columns', [])}
Sonuç: {active_context.get('result_row_count', 0)} satır"""
            else:
                context_info = "YOK (yeni oturum)"

            # Conversation history formatla (son 5 mesaj)
            history_lines = []
            recent_messages = messages[-5:] if len(messages) > 5 else messages
            for msg in recent_messages:
                role = "Kullanıcı" if isinstance(msg, HumanMessage) else "Asistan"
                content = str(msg.content)[:150]
                history_lines.append(f"[{role}]: {content}")
            conversation_history = "\n".join(history_lines) if history_lines else "(Geçmiş yok)"

            # Prompt oluştur
            formatted_prompt = prompt.format(
                context_info=context_info,
                intent_type=intent_type,
                confidence=confidence,
                extracted_entities=json.dumps(extracted_entities, ensure_ascii=False),
                waiting_for_input=waiting_for_input,
                conversation_history=conversation_history,
                user_message=user_message
            )

            # LLM çağır
            logger.info("[REPORT] Invoking LLM for smart routing decision...")
            response = await llm.ainvoke(formatted_prompt)
            response_text = response.content.strip()

            # JSON parse et
            # Code block içindeyse çıkar
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                json_lines = [l for l in lines if not l.startswith("```")]
                response_text = "\n".join(json_lines)

            result = json.loads(response_text)
            route = result.get("route", "process_query")
            reason = result.get("reason", "")

            logger.info(f"[REPORT] LLM routing decision: {route} - {reason}")

            # Clarification sorusu varsa state'e ekle
            clarification = result.get("clarification_needed")
            if route == "ask_user" and clarification:
                # Bu bilgi bir sonraki node'da kullanılabilir
                logger.info(f"[REPORT] Clarification question: {clarification}")

            # Geçerli route mu kontrol et
            if route in ["ask_user", "rollback", "visualize_direct", "process_query"]:
                return route
            else:
                logger.warning(f"[REPORT] Invalid route from LLM: {route}, defaulting to process_query")
                return "process_query"

        except json.JSONDecodeError as e:
            logger.warning(f"[REPORT] JSON parse error in routing: {e}")
            # Fallback: basit kurallara göre karar
            return _fallback_route_decision(intent_type, confidence)
        except Exception as e:
            logger.error(f"[REPORT] LLM routing error: {e}")
            # Fallback: basit kurallara göre karar
            return _fallback_route_decision(intent_type, confidence)

    return smart_route_after_intent


def _fallback_route_decision(intent_type: str, confidence: float) -> str:
    """
    LLM başarısız olduğunda basit kural tabanlı routing.

    Args:
        intent_type: Tespit edilen intent
        confidence: Güven skoru

    Returns:
        Route string
    """
    if intent_type == "rollback":
        return "rollback"

    if confidence < 0.5:
        return "ask_user"

    return "process_query"


def route_after_intent_classification(state: ReportState) -> str:
    """
    Router after intent classification (Phase 3).

    CRITICAL: Checks if query type clarification is needed.

    Routes:
        "ask_user_clarification" → Query type ambiguous, needs user input
        "process_query" → Query type clear, continue to Text2SQL

    Args:
        state: ReportState

    Returns:
        Next node name
    """
    needs_clarification = state.get("_needs_clarification", False)

    if needs_clarification:
        query_type = state.get("query_type", "unknown")
        confidence = state.get("query_type_confidence", 0.0)
        logger.info(f"[ROUTER] Query type unclear (type={query_type}, conf={confidence:.2f}), "
                   f"routing to ask_user_clarification")
        return "ask_user_clarification"

    logger.info("[ROUTER] Query type clear, routing to process_query")
    return "process_query"


def route_after_intent(state: ReportState) -> str:
    """
    Basit kural tabanlı routing (LLM olmadan fallback).

    Bu fonksiyon LLM router kullanılamadığında veya
    hızlı yol gerektiğinde kullanılır.

    Returns:
        Next node name
    """
    # HITL bekliyor mu?
    if state.get("waiting_for_user_input"):
        logger.info("[REPORT] Routing to ask_user (waiting for input)")
        return "ask_user"

    # Intent type'a göre route et
    intent_type = state.get("_intent_type", "new_query")
    confidence = state.get("_confidence", 0.0)
    extracted_entities = state.get("_extracted_entities", {})

    logger.info(f"[REPORT] Routing decision: intent={intent_type}, confidence={confidence}")
    logger.debug(f"[REPORT] Extracted entities: {extracted_entities}")

    if intent_type == "rollback":
        logger.info("[REPORT] Routing to rollback")
        return "rollback"

    # VISUALIZE intent: Text2SQL'i atla, direkt decide_visualization'a git
    # Mevcut context'teki sonuçları kullan, sadece grafik render et
    if intent_type == "visualize":
        logger.info("[REPORT] Routing to visualize_direct (skip text2sql for chart conversion)")
        return "visualize_direct"

    # Metadata clarification sonrası retry
    if intent_type == "retry_with_clarification":
        logger.info("[REPORT] Routing to extract_query (retry with user clarification)")
        return "extract_query"

    # new_query, modify_filter, modify_aggregation, modify_order, modify_columns
    # hepsi extract_query'ye gidiyor (text2sql ile işlenecek)
    logger.info(f"[REPORT] Routing to extract_query (intent: {intent_type})")
    return "extract_query"


def route_after_intent_smart(state: ReportState) -> str:
    """
    Smart routing with execution mode detection (Phase 1).

    Determines execution path based on:
    - Intent type
    - Conversation context
    - Active query context
    - Confidence scores

    Returns:
        Next node name: "extract_query" | "ask_user" | "rollback" | "visualize_direct"
    """
    # HITL bekliyor mu?
    if state.get("waiting_for_user_input"):
        logger.info("[REPORT] [SMART_ROUTER] Routing to ask_user (waiting for input)")
        return "ask_user"

    intent_type = state.get("_intent_type", "new_query")
    confidence = state.get("_confidence", 0.0)
    active_context = state.get("active_query_context")
    last_intent = state.get("last_intent")

    logger.info(f"[REPORT] [SMART_ROUTER] Intent: {intent_type}, Confidence: {confidence:.2f}")

    # Rollback
    if intent_type == "rollback":
        logger.info("[REPORT] [SMART_ROUTER] → rollback")
        return "rollback"

    # Visualize existing data (skip Text2SQL)
    if intent_type == "visualize":
        logger.info("[REPORT] [SMART_ROUTER] → visualize_direct (skip Text2SQL)")
        return "visualize_direct"

    # For Phase 1, all queries go to extract_query
    # extract_query_node will determine execution mode
    logger.info("[REPORT] [SMART_ROUTER] → extract_query")
    return "extract_query"


def _determine_execution_mode(
    intent_type: str,
    active_context: Optional[Dict[str, Any]],
    last_intent: Optional[str],
    confidence: float
) -> str:
    """
    Determine execution mode based on conversation context.

    Execution Modes:
    - "full": Complete query execution (new query, no context)
    - "contextual_full": Full SQL rebuild with context preservation (RECOMMENDED for modify_filter)
    - "delta": Incremental SQL modification (legacy, can cause SQL errors)
    - "reuse": Reuse existing data (visualization change only)

    CRITICAL: contextual_full is more reliable than delta for filter modifications
    because it rebuilds SQL from scratch while preserving context.

    Returns:
        Execution mode: "full" | "contextual_full" | "delta" | "reuse"
    """
    # No active context → Full execution
    if not active_context:
        logger.debug("[EXECUTION_MODE] No active context → full")
        return "full"

    # Low confidence → Full execution (safer)
    if confidence < 0.7:
        logger.debug(f"[EXECUTION_MODE] Low confidence ({confidence:.2f}) → full")
        return "full"

    # Intent types that suggest context-aware full rebuild (SAFER than delta)
    contextual_full_intents = {
        "modify_filter",      # ✅ Use contextual_full (avoids SQL syntax errors)
        "add_filter",         # ✅ Use contextual_full
        "remove_filter",      # ✅ Use contextual_full
    }

    # Intent types that can use delta (simpler modifications)
    delta_only_intents = {
        "modify_aggregation",  # GROUP BY changes
        "modify_columns",      # SELECT column changes
        "modify_order",        # ORDER BY changes
    }

    if intent_type in contextual_full_intents:
        logger.debug(f"[EXECUTION_MODE] Filter modification '{intent_type}' → contextual_full (safer)")
        return "contextual_full"  # Rebuild SQL with context

    if intent_type in delta_only_intents:
        logger.debug(f"[EXECUTION_MODE] Delta intent '{intent_type}' detected → delta")
        return "delta"  # Use delta for non-filter changes

    # Visualization change only
    if intent_type == "visualize" and last_intent in ["new_query", "modify_filter"]:
        logger.debug("[EXECUTION_MODE] Visualization change → reuse (Phase 2)")
        return "reuse"  # Phase 2 will use this

    # Default: Full execution
    logger.debug(f"[EXECUTION_MODE] Intent '{intent_type}' → full")
    return "full"


def route_after_results(state: ReportState) -> str:
    """
    Results check sonrası routing.

    Returns:
        Next node name
    """
    # HITL bekliyor mu? (empty result recovery)
    if state.get("waiting_for_user_input"):
        return "ask_user"

    # Boş sonuç mesajı varsa visualization atla
    if state.get("no_records_message"):
        return "build_response"

    # Hata varsa
    if state.get("error"):
        return "build_response"

    # Success → Go to visualization decision
    return "decide_visualization"


# =============================================================================
# LLM-ENHANCED NODE FACTORIES (New Architecture)
# =============================================================================

def create_conversation_aware_intent_node(conversation_manager):
    """
    Factory for LLM-powered intent understanding node.

    Uses ConversationManager instead of IntentClassifier for:
    - Full LLM intent understanding (not just classification)
    - Business context reasoning
    - Smart clarification generation

    Args:
        conversation_manager: ConversationManager instance

    Returns:
        Enhanced intent classification node
    """
    async def conversation_aware_intent_node(state: ReportState) -> Dict[str, Any]:
        """
        LLM-powered intent understanding with conversation awareness.
        """
        user_message = get_last_user_message(state)
        if not user_message:
            return {"error": "No user message found"}

        logger.info(f"[REPORT] [LLM] Understanding intent: {user_message[:50]}...")

        active_context = state.get("active_query_context")
        messages = state.get("messages", [])
        business_context = state.get("business_context")

        try:
            # Use ConversationManager for enhanced understanding
            intent = await conversation_manager.understand_intent(
                user_message=user_message,
                active_context=active_context,
                conversation_history=messages,
                business_context=business_context
            )

            logger.info(f"[REPORT] [LLM] Intent: {intent.intent_type}, Confidence: {intent.confidence:.2f}")
            logger.debug(f"[REPORT] [LLM] Reasoning: {intent.reasoning[:100]}...")

            # Check clarification
            if intent.requires_clarification:
                logger.info("[REPORT] [LLM] Clarification required")
                clarification = create_clarification_request(
                    question=intent.clarification_question or "Lütfen açıklayın:",
                    options=intent.clarification_options or ["Devam et", "İptal"],
                    context=f"Intent: {intent.intent_type.value}"
                )
                # FIXED: Add user_query to clarification return
                clarification["user_query"] = user_message
                return clarification

            # =====================================================================
            # PHASE 2: CONTEXT-AWARE QUERY ANALYSIS (LLM-DRIVEN)
            # =====================================================================
            conversation_history = state.get("conversation_history", [])
            last_query_results = state.get("last_query_results")

            # Get LLM from conversation_manager
            llm = conversation_manager.llm if hasattr(conversation_manager, 'llm') else None

            # Default query analysis
            query_analysis = {
                "query_type": None,
                "confidence": 0.0,
                "is_followup": False,
                "needs_clarification": False,
                "reference_context": {}
            }

            if llm:
                logger.info("[PHASE2] LLM available, running context-aware query analysis...")
                try:
                    query_analysis = await _analyze_query_with_context(
                        user_message=user_message,
                        active_context=active_context,
                        conversation_history=conversation_history,
                        last_query_results=last_query_results,
                        llm=llm
                    )
                    logger.info(f"[PHASE2] [QUERY_ANALYSIS] Result: type={query_analysis.get('query_type')}, "
                               f"conf={query_analysis.get('confidence', 0):.2f}, "
                               f"followup={query_analysis.get('is_followup', False)}")
                except Exception as e:
                    logger.error(f"[PHASE2] [QUERY_ANALYSIS] Failed: {e}", exc_info=True)
            else:
                logger.warning("[PHASE2] LLM not available, skipping query analysis")

            should_ask_user = query_analysis.get("needs_clarification", False)

            # Return enhanced intent info
            return {
                "user_query": user_message,  # FIXED: Add user_query (missing field)
                "_intent_type": intent.intent_type.value,
                "_confidence": intent.confidence,
                "_extracted_entities": intent.extracted_entities,
                "_intent_reasoning": intent.reasoning,  # LLM reasoning trace
                # Phase 2: NEW fields
                "query_type": query_analysis.get("query_type"),
                "query_type_confidence": query_analysis.get("confidence", 0.0),
                "reference_context": query_analysis.get("reference_context", {}),
                "_needs_clarification": should_ask_user,
            }

        except Exception as e:
            logger.error(f"[REPORT] [LLM] Intent understanding error: {e}")
            # Fallback to simple classification
            return {
                "_intent_type": "new_query",
                "_confidence": 0.5,
                "_extracted_entities": {},
                "_intent_reasoning": f"Error: {e}",
                # Phase 2: Default values on error
                "query_type": None,
                "query_type_confidence": 0.0,
                "reference_context": {},
                "_needs_clarification": False,
            }

    return conversation_aware_intent_node


def create_business_insights_node(business_context_tracker):
    """
    Factory for business insights extraction node.

    Extracts business-level insights from query results.

    Args:
        business_context_tracker: BusinessContextTracker instance

    Returns:
        Business insights extraction node
    """
    async def extract_business_insights_node(state: ReportState) -> Dict[str, Any]:
        """
        Extract business insights from query results.
        """
        text2sql_output = state.get("text2sql_output")
        if not text2sql_output or text2sql_output.get("error"):
            logger.info("[REPORT] [LLM] No valid results for business insights")
            return {}

        user_message = get_last_user_message(state)
        results = text2sql_output.get("results", [])
        active_context = state.get("active_query_context")
        previous_business_context = state.get("business_context")

        if not results:
            logger.info("[REPORT] [LLM] Empty results, skipping insights")
            return {}

        logger.info(f"[REPORT] [LLM] Extracting business insights from {len(results)} results...")

        try:
            business_context = await business_context_tracker.extract_insights(
                user_query=user_message or "",
                data_results=results,
                active_context=active_context,
                previous_business_context=previous_business_context
            )

            logger.info(f"[REPORT] [LLM] Extracted {len(business_context['key_insights'])} insights")

            return {
                "business_context": business_context
            }

        except Exception as e:
            logger.error(f"[REPORT] [LLM] Business insights extraction error: {e}")
            return {}

    return extract_business_insights_node


def create_llm_viz_decision_node(report_interpreter):
    """
    Factory for LLM-assisted visualization decision node.

    Replaces rule-based decide_visualization_node with LLM reasoning.

    Args:
        report_interpreter: ReportInterpreter instance

    Returns:
        LLM-powered visualization decision node
    """
    async def decide_visualization_llm_node(state: ReportState) -> Dict[str, Any]:
        """
        LLM-powered visualization decision.
        """
        text2sql_output = state.get("text2sql_output")
        if not text2sql_output or text2sql_output.get("error"):
            logger.info("[REPORT] [LLM] No valid results for visualization decision")
            return {}

        user_query = get_last_user_message(state) or ""
        results = text2sql_output.get("results", [])
        active_context = state.get("active_query_context")

        logger.info(f"[REPORT] [LLM] Deciding visualization for {len(results)} results...")

        try:
            interpretation = await report_interpreter.interpret_results(
                user_query=user_query,
                data_results=results,
                active_context=active_context
            )

            logger.info(f"[REPORT] [LLM] Decision: {interpretation.output_type} (needs_graph={interpretation.needs_graph})")
            logger.debug(f"[REPORT] [LLM] Reasoning: {interpretation.reason}")

            return {
                "_viz_decision": interpretation.dict(),
                "_viz_reasoning": interpretation.reasoning  # NEW: LLM reasoning trace
            }

        except Exception as e:
            logger.error(f"[REPORT] [LLM] Visualization decision error: {e}")
            # Fallback to rule-based
            return await decide_visualization_node(state)

    return decide_visualization_llm_node


def create_parallel_insights_viz_node(business_tracker, report_interpreter):
    """
    Factory for parallel insights + viz decision node.

    PHASE 1 OPTIMIZATION: Run business insights and viz decision in PARALLEL
    instead of sequential. Expected savings: ~700ms.

    Args:
        business_tracker: BusinessContextTracker instance (optional)
        report_interpreter: ReportInterpreter instance (optional)

    Returns:
        Parallel execution node
    """
    import asyncio
    import time

    async def parallel_insights_viz_node(state: ReportState) -> Dict[str, Any]:
        """
        Run business insights and viz decision in PARALLEL.

        This node replaces the sequential execution of:
        1. extract_business_insights → decide_visualization

        With parallel execution:
        1. extract_business_insights + decide_visualization (concurrent)

        Expected savings: ~700ms (from ~1.5s sequential to ~0.8s parallel)
        """
        text2sql_output = state.get("text2sql_output")
        if not text2sql_output or text2sql_output.get("error"):
            logger.info("[REPORT] No valid results for parallel processing")
            return {}

        user_message = get_last_user_message(state) or ""
        results = text2sql_output.get("results", [])
        active_context = state.get("active_query_context")
        previous_business_context = state.get("business_context")

        if not results:
            logger.info("[REPORT] Empty results, skipping parallel processing")
            return {}

        # Prepare tasks
        tasks = []
        task_names = []

        # Task 1: Business insights (if enabled)
        if business_tracker:
            async def extract_insights():
                try:
                    return await business_tracker.extract_insights(
                        user_query=user_message,
                        data_results=results,
                        active_context=active_context,
                        previous_business_context=previous_business_context
                    )
                except Exception as e:
                    logger.error(f"[REPORT] Business insights extraction error: {e}")
                    return None

            tasks.append(extract_insights())
            task_names.append("business_insights")

        # Task 2: Viz decision (if enabled)
        if report_interpreter:
            async def decide_viz():
                try:
                    return await report_interpreter.interpret_results(
                        user_query=user_message,
                        data_results=results,
                        active_context=active_context
                    )
                except Exception as e:
                    logger.error(f"[REPORT] Viz decision error: {e}")
                    return None

            tasks.append(decide_viz())
            task_names.append("viz_decision")

        if not tasks:
            logger.info("[REPORT] No parallel tasks to run")
            return {}

        # Execute in PARALLEL
        logger.info(f"[REPORT] ⚡ Running {len(tasks)} tasks in PARALLEL: {task_names}")
        start_time = time.time()

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.time() - start_time
        logger.info(f"[REPORT] ⚡ Parallel execution completed in {elapsed:.2f}s (saved ~{max(0, len(tasks) * 0.7 - elapsed):.2f}s)")

        # Build return dict
        ret = {}

        for i, (task_name, result) in enumerate(zip(task_names, results_list)):
            if isinstance(result, Exception):
                logger.error(f"[REPORT] Task {task_name} failed: {result}")
                continue

            if result is None:
                logger.warning(f"[REPORT] Task {task_name} returned None")
                continue

            if task_name == "business_insights":
                ret["business_context"] = result
                logger.info(f"[REPORT] ✓ Business insights extracted: {len(result.get('key_insights', []))} insights")
            elif task_name == "viz_decision":
                ret["_viz_decision"] = result.dict()
                ret["_viz_reasoning"] = result.reasoning
                logger.info(f"[REPORT] ✓ Viz decision: {result.output_type} (needs_graph={result.needs_graph})")

        return ret

    return parallel_insights_viz_node


def create_natural_response_node(response_generator):
    """
    Factory for natural language response generation node.

    Replaces template-based build_response_node with LLM generation.

    Args:
        response_generator: ResponseGenerator instance

    Returns:
        Natural response generation node
    """
    async def build_natural_response_node(state: ReportState) -> Dict[str, Any]:
        """
        Generate natural language response with insights.
        """
        user_query = get_last_user_message(state) or ""
        viz_output = state.get("visualization_output")
        text2sql_output = state.get("text2sql_output")
        business_context = state.get("business_context")
        viz_decision = state.get("_viz_decision")
        error = state.get("error")
        no_records = state.get("no_records_message")

        logger.info("[REPORT] [LLM] Generating natural language response...")

        try:
            # Extract data results - support both merged mode and backward compatibility
            data_results = None

            # Merged mode: check direct state fields first
            if state.get("results") is not None:
                data_results = state.get("results", [])
                logger.info(f"[REPORT] [LLM] Using merged mode results: {len(data_results)} rows")
            # Backward compatibility: check text2sql_output
            elif text2sql_output and not text2sql_output.get("error"):
                data_results = text2sql_output.get("results", [])
                logger.info(f"[REPORT] [LLM] Using backward compatibility results: {len(data_results)} rows")

            # Generate response
            response = await response_generator.generate_response(
                user_query=user_query,
                data_results=data_results,
                business_context=business_context,
                visualization_info=viz_decision,
                error=error,
                no_records_message=no_records
            )

            logger.info(f"[REPORT] [LLM] Generated response: {len(response)} chars")

            # Handle visualization output (Plotly HTML)
            plotly_html = viz_output.get("plotly_html_snippet") if viz_output else None
            if plotly_html and viz_decision and viz_decision.get("needs_graph"):
                import base64
                html_full = f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0">{plotly_html}</body></html>'''
                html_b64 = base64.b64encode(html_full.encode('utf-8')).decode('ascii')
                iframe = f'<iframe src="data:text/html;charset=utf-8;base64,{html_b64}" width="100%" height="500" frameborder="0"></iframe>'
                response = f"{response}\n\n📈 **Grafik:**\n{iframe}"

            return {
                "messages": [AIMessage(content=response)],
                "_response_reasoning": "LLM-generated natural response"  # NEW: Reasoning trace
            }

        except Exception as e:
            logger.error(f"[REPORT] [LLM] Response generation error: {e}")
            # Fallback to template-based
            return await build_response_node(state)

    return build_natural_response_node


# =============================================================================
# ENHANCED HITL - CLARIFICATION PROCESSORS (v2.0)
# =============================================================================

async def _process_enhanced_clarification(
    state: ReportState,
    ambiguity_ctx: Any,  # AmbiguityContext
    user_response: str
) -> Dict[str, Any]:
    """
    Process user clarification using enhanced ambiguity system.

    Routes to type-specific processor based on ambiguity_type.

    Args:
        state: Current ReportState
        ambiguity_ctx: AmbiguityContext from detection
        user_response: User's clarification response

    Returns:
        State updates dict
    """
    from .ambiguity_framework import AmbiguityType

    # Common result template
    result = {
        "pending_question": None,
        "waiting_for_user_input": False,
        "user_clarification": None,
        "ambiguity_context": None,  # Clear after processing
    }

    # Route to type-specific processor
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
        logger.warning(f"[HITL] Unknown ambiguity type: {ambiguity_type}")
        updates = {"_intent_type": "new_query"}

    return {**result, **updates}


def _process_context_clarification(
    state: ReportState,
    ambiguity_ctx: Any,
    user_response: str
) -> Dict[str, Any]:
    """
    Process context ambiguity clarification (MOST CRITICAL).

    User choice:
    - Option 1 (keep filters): execution_mode=delta, intent=modify_filter
    - Option 2 (clear filters): clear context, intent=new_query

    Args:
        state: Current ReportState
        ambiguity_ctx: AmbiguityContext with type=CONTEXT
        user_response: User's choice

    Returns:
        State updates dict

    Example:
        User chose "Evet, Ankara + Son 3 yıl için kategorilere göre göster"
        → Keep filters, execution_mode=delta
    """
    response_lower = user_response.lower()

    # Parse response (option number or keywords)
    keep_filters = False

    # Option 1: Keep filters
    if "1" in user_response or "evet" in response_lower or "koru" in response_lower:
        keep_filters = True

    # Option 2: Clear filters
    elif "2" in user_response or "hayır" in response_lower or "tüm" in response_lower:
        keep_filters = False

    else:
        # Default: keep filters (safe choice) but inform user
        logger.warning(f"[HITL] Unclear response: '{user_response}', defaulting to keep filters")

        # ✅ Inform user about unclear response
        from langchain_core.messages import AIMessage
        return {
            "messages": [AIMessage(content=(
                "⚠️ Cevabınızı tam anlayamadım. Filtreleri koruyorum.\n\n"
                "💡 İpucu: Gelecekte '1' veya '2' yazabilirsiniz."
            ))],
            "_intent_type": "modify_filter",
            "_execution_mode": "contextual_full",
            "_preserve_context": True
        }
        # keep_filters = True  # Removed - handled in return above

    if keep_filters:
        logger.info("[HITL] User chose to KEEP filters (contextual_full mode)")

        # ⚠️ CRITICAL: Preserve active_query_context!
        # When user says "continue with filters", we MUST keep the context
        active_context = state.get("active_query_context")

        if not active_context:
            logger.warning("[HITL] No active context to keep, treating as new query")
            return {
                "_execution_mode": "full",
                "_intent_type": "new_query",
                "user_query": state.get("user_query", "")
            }

        # Use contextual_full mode (enriches query with context filters)
        # This will trigger context-aware full rebuild in extract_query_node
        return {
            "_execution_mode": "contextual_full",
            "_intent_type": "modify_filter",
            "user_query": state.get("user_query", ""),
            # ⚠️ CRITICAL: Explicitly preserve context!
            # This ensures filters are maintained throughout execution
            "_preserve_context": True,
            "_context_filters_to_keep": active_context.get("applied_filters", []),
            "_context_grouping_to_keep": active_context.get("grouping_columns", [])
        }
    else:
        logger.info("[HITL] User chose to CLEAR filters (new query)")
        return {
            "_execution_mode": "full",
            "_intent_type": "new_query",
            "active_query_context": None,  # Clear context
            "user_query": state.get("user_query", "")
        }


def _process_prompt_scope_clarification(
    state: ReportState,
    ambiguity_ctx: Any,
    user_response: str
) -> Dict[str, Any]:
    """
    Process prompt scope ambiguity clarification.

    User chose a clarification option to refine vague query.

    Args:
        state: Current ReportState
        ambiguity_ctx: AmbiguityContext with type=PROMPT_SCOPE
        user_response: User's choice

    Returns:
        State updates dict

    Example:
        Original query: "Satışlar"
        User chose: "Tüm satış kayıtlarını listele"
        → Enhanced query for processing
    """
    response_lower = user_response.lower()

    # Parse option number
    option_mapping = {
        "1": "list_all",
        "2": "summary_stats",
        "3": "filtered",
        "4": "grouped"
    }

    # Detect option
    scope_type = "list_all"  # Default

    for key, value in option_mapping.items():
        if key in user_response:
            scope_type = value
            break

    # Enhance user query based on scope
    original_query = state.get("user_query", "")

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

    logger.info(f"[HITL] Prompt scope clarified: {scope_type}")

    return {
        "_intent_type": "new_query",
        "user_query": enhanced_query,  # Enhanced query
        "_extracted_entities": {"prompt_scope": scope_type}
    }


def _process_intent_clarification(
    state: ReportState,
    ambiguity_ctx: Any,
    user_response: str
) -> Dict[str, Any]:
    """
    Process intent ambiguity clarification.

    User chose what they want to do.

    Args:
        state: Current ReportState
        ambiguity_ctx: AmbiguityContext with type=INTENT
        user_response: User's choice

    Returns:
        State updates dict
    """
    response_lower = user_response.lower()

    # Map response to intent
    if "yeni" in response_lower or "oluştur" in response_lower or "1" in user_response:
        intent_type = "new_query"
    elif "değiştir" in response_lower or "filtre" in response_lower or "2" in user_response:
        intent_type = "modify_filter"
    elif "kolon" in response_lower or "ekle" in response_lower or "3" in user_response:
        intent_type = "modify_columns"
    elif "geri" in response_lower or "undo" in response_lower:
        intent_type = "rollback"
    else:
        # Default
        intent_type = "new_query"

    logger.info(f"[HITL] Intent clarified: {intent_type}")

    return {
        "_intent_type": intent_type
    }


def _process_column_clarification(
    state: ReportState,
    ambiguity_ctx: Any,
    user_response: str
) -> Dict[str, Any]:
    """
    Process column ambiguity clarification.

    User selected which column to use.

    Args:
        state: Current ReportState
        ambiguity_ctx: AmbiguityContext with type=COLUMN
        user_response: User's choice

    Returns:
        State updates dict
    """
    # Parse option number or direct column name
    candidates = ambiguity_ctx.candidates
    selected_column = None

    # Try to parse option number
    for i, candidate in enumerate(candidates, 1):
        if str(i) in user_response:
            selected_column = candidate
            break

    # If no match, use user response directly
    if not selected_column:
        selected_column = user_response.strip()

    logger.info(f"[HITL] Column clarified: {selected_column}")

    return {
        "_selected_column": selected_column,
        "_clarification_type": "column",
        "_intent_type": "retry_with_clarification"
    }


def _process_value_clarification(
    state: ReportState,
    ambiguity_ctx: Any,
    user_response: str
) -> Dict[str, Any]:
    """
    Process value ambiguity clarification.

    User selected which value to use.

    Args:
        state: Current ReportState
        ambiguity_ctx: AmbiguityContext with type=VALUE
        user_response: User's choice

    Returns:
        State updates dict
    """
    # Parse option number or direct value
    candidates = ambiguity_ctx.candidates
    selected_value = None

    # Try to parse option number
    for i, candidate in enumerate(candidates, 1):
        if str(i) in user_response:
            selected_value = candidate
            break

    # If no match, use user response directly
    if not selected_value:
        selected_value = user_response.strip()

    logger.info(f"[HITL] Value clarified: {selected_value}")

    return {
        "_selected_value": selected_value,
        "_clarification_type": "value",
        "_intent_type": "retry_with_clarification"
    }


def _process_legacy_clarification(
    state: ReportState,
    user_response: str,
    pending_question: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Process clarification using legacy system (backward compatibility).

    This preserves all existing HITL logic for users not using enhanced system.

    Args:
        state: Current ReportState
        user_response: User's clarification response
        pending_question: Pending question from state

    Returns:
        State updates dict
    """
    # Yanıta göre intent'i belirle
    response_lower = user_response.lower()
    result = {
        "pending_question": None,
        "waiting_for_user_input": False,
        "user_clarification": None
    }

    # Pending question context'ine göre analiz et
    question_context = pending_question.get("context", "") if pending_question else ""
    question_text = pending_question.get("question", "") if pending_question else ""

    # =========================================================================
    # USER PREFERENCES CLARIFICATION
    # =========================================================================
    if "tercihleri" in question_text or "tercihleriniz" in question_text:
        logger.info(f"[REPORT] User preference received: {user_response}")
        # Tercihi _user_preference olarak kaydet
        result["_user_preference"] = user_response
        result["_preference_type"] = "date_range" if "gün" in user_response or "ay" in user_response or "yıl" in user_response else "general"
        result["_intent_type"] = "new_query"  # Tercih alındı, sorguya devam et
        logger.info(f"[REPORT] User preference set: {user_response}")
        return result

    # =========================================================================
    # "DID YOU MEAN" CLARIFICATION
    # =========================================================================
    if "demek istediniz" in question_text or "kullanılsın mı" in question_text:
        logger.info(f"[REPORT] 'Did you mean' clarification received: {user_response}")

        if "evet" in response_lower or "doğru" in response_lower:
            # Kullanıcı öneriyi kabul etti
            # Pending question'dan suggested field'ı çıkar
            if pending_question:
                question_parts = pending_question.get("question", "").split("'")
                if len(question_parts) >= 4:
                    suggested_value = question_parts[3]  # "... 'suggested_value' ..."
                    result["_selected_value"] = suggested_value
                    result["_clarification_type"] = "value"
                    result["_intent_type"] = "retry_with_clarification"
                    logger.info(f"[REPORT] User accepted suggestion: {suggested_value}")
        else:
            # Kullanıcı öneriyi reddetti, tam olarak yazdığını kullan
            result["_use_exact_input"] = True
            result["_intent_type"] = "new_query"
            logger.info("[REPORT] User rejected suggestion, using exact input")

        return result

    # =========================================================================
    # METADATA AMBIGUITY - Column/Value Clarification
    # =========================================================================
    # "için hangi kolonu" veya "için hangi değeri" ifadeleri metadata ambiguity sorusu
    if "için hangi kolonu" in question_text or "birden fazla kolon" in question_context:
        # Column ambiguity clarification
        logger.info(f"[REPORT] Column ambiguity clarification received: {user_response}")
        result["_selected_column"] = user_response
        result["_clarification_type"] = "column"
        # Text2SQL'i tekrar çalıştırmak için intent set et
        result["_intent_type"] = "retry_with_clarification"
        return result

    if "için hangi değeri" in question_text or "için birden fazla eşleşme" in question_context:
        # Value ambiguity clarification
        logger.info(f"[REPORT] Value ambiguity clarification received: {user_response}")
        result["_selected_value"] = user_response
        result["_clarification_type"] = "value"
        # Text2SQL'i tekrar çalıştırmak için intent set et
        result["_intent_type"] = "retry_with_clarification"
        return result

    # =========================================================================
    # REGULAR CLARIFICATIONS (Empty Result, Modification Type, etc.)
    # =========================================================================

    # Empty result recovery sorusu için
    if "boş sonuç" in question_context.lower() or "veri bulunamadı" in question_context.lower():
        if "geri" in response_lower or "önceki" in response_lower:
            result["_intent_type"] = IntentType.ROLLBACK.value
            logger.info("[REPORT] User chose rollback after empty result")
        elif "genişlet" in response_lower or "filtre" in response_lower:
            result["_intent_type"] = IntentType.MODIFY_FILTER.value
            result["_modification_action"] = "expand_filter"
            logger.info("[REPORT] User chose to expand filter")
        else:
            result["_intent_type"] = IntentType.NEW_QUERY.value
            logger.info("[REPORT] User chose new query")
        return result

    # Tablo belirsizliği için
    if "hangi tablo" in question_context.lower():
        # Kullanıcının seçtiği tablo adını kaydet
        result["_selected_table"] = user_response
        result["_intent_type"] = IntentType.NEW_QUERY.value
        logger.info(f"[REPORT] User selected table: {user_response}")
        return result

    # Filtre değeri belirsizliği için
    if "hangi değer" in question_context.lower() or "için birden fazla" in question_context.lower():
        result["_selected_filter_value"] = user_response
        result["_intent_type"] = IntentType.MODIFY_FILTER.value
        logger.info(f"[REPORT] User selected filter value: {user_response}")
        return result

    # Modifikasyon tipi belirsizliği için
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

    # Genel fallback
    if "yeni" in response_lower or "oluştur" in response_lower:
        result["_intent_type"] = IntentType.NEW_QUERY.value
    elif "değiştir" in response_lower or "ekle" in response_lower:
        result["_intent_type"] = IntentType.MODIFY_FILTER.value
    elif "geri" in response_lower or "önceki" in response_lower:
        result["_intent_type"] = IntentType.ROLLBACK.value
    else:
        result["_intent_type"] = IntentType.NEW_QUERY.value

    return result
