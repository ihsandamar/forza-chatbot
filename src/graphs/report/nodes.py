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

logger = logging.getLogger(__name__)


# =============================================================================
# VISUALIZATION DECISION (Moved from data_visualization graph)
# =============================================================================

async def decide_visualization_node(state: ReportState) -> Dict[str, Any]:
    """
    Görselleştirme kararı ver (data_visualization graph'tan alındı).

    Karar logic'i artık report graph'ta.
    Visualization graph sadece render yapar.
    """
    text2sql_output = state.get("text2sql_output")

    if not text2sql_output or text2sql_output.get("error"):
        logger.info("[REPORT] No text2sql output for visualization decision")
        return {}

    results = text2sql_output.get("results", [])

    if not results or len(results) == 0:
        logger.info("[REPORT] No results for visualization")
        return {
            "_viz_decision": {
                "needs_graph": False,
                "output_type": "table",
                "reason": "Sonuç yok"
            }
        }

    # Quick decisions without LLM
    # 1. Single value
    if len(results) == 1 and len(results[0].keys()) == 1:
        logger.info("[REPORT] Single value detected, no graph needed")
        return {
            "_viz_decision": {
                "needs_graph": False,
                "output_type": "single_value",
                "reason": "Tek değer sonucu"
            }
        }

    # 2. Check user query for explicit chart type
    user_query = get_last_user_message(state) or ""
    user_query_lower = user_query.lower()

    chart_type_keywords = {
        "bar": ["çubuk", "bar", "막대"],
        "line": ["çizgi", "line", "trend"],
        "pie": ["pasta", "pie", "daire", "oran"],
        "scatter": ["scatter", "dağılım"],
        "sunburst": ["sunburst", "hiyerarşik"],
        "treemap": ["treemap", "ağaç"]
    }

    detected_chart_type = None
    for chart_type, keywords in chart_type_keywords.items():
        if any(kw in user_query_lower for kw in keywords):
            detected_chart_type = f"{chart_type}_chart"
            logger.info(f"[REPORT] User explicitly requested: {detected_chart_type}")
            break

    if detected_chart_type:
        return {
            "_viz_decision": {
                "needs_graph": True,
                "output_type": detected_chart_type,
                "reason": f"Kullanıcı {detected_chart_type} istedi"
            }
        }

    # 3. Default: ALWAYS LIST/TABLE (grafik sadece explicit istek)
    # Kullanıcı grafik istemediyse, her zaman liste öncelikli
    if len(results) > 1:
        if len(results) <= 20:
            output_type = "simple_list"
            reason = "Liste gösterimi (kullanıcı grafik belirtmedi)"
        else:
            output_type = "table"
            reason = "Tablo gösterimi (çok satır)"

        logger.info(f"[REPORT] Default decision: {output_type} (no graph)")
        return {
            "_viz_decision": {
                "needs_graph": False,
                "output_type": output_type,
                "reason": reason
            }
        }

    # Fallback: simple_list or table
    return {
        "_viz_decision": {
            "needs_graph": False,
            "output_type": "simple_list" if len(results) <= 5 else "table",
            "reason": "Liste gösterimi (varsayılan)"
        }
    }


# =============================================================================
# EXISTING NODE FUNCTIONS
# =============================================================================


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

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
    """
    logger.info("[REPORT] Sending immediate acknowledgment")

    return {
        "messages": [AIMessage(content="🔄 Sorgunuz işleniyor...")]
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
                        "_intent_type": "new_query",
                        "_confidence": 0.85,
                        "_extracted_entities": {},
                        "_intent_reasoning": "Fast path: Simple query pattern"
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
        # INTENT CLARIFICATION (Only when ambiguous)
        # =========================================================================
        # HITL gerekiyor mu?
        if classification.requires_clarification:
            logger.info("[REPORT] Clarification required, preparing HITL")

            # Soru oluştur
            if classification.clarification_question:
                question = classification.clarification_question
                options = classification.clarification_options or ["Evet", "Hayır"]
            else:
                # Default question based on intent type
                question = "Ne yapmak istediğinizi tam anlayamadım."
                options = ["Yeni rapor oluştur", "Mevcut raporu değiştir"]

            return create_clarification_request(
                question=question,
                options=options,
                context=f"Tespit edilen niyet: {classification.intent_type.value}"
            )

        # Classification bilgisini state'e kaydet
        return {
            "_intent_type": classification.intent_type.value,
            "_confidence": classification.confidence,
            "_extracted_entities": classification.extracted_entities
        }

    return classify_intent_node


async def process_user_clarification_node(state: ReportState) -> Dict[str, Any]:
    """
    Kullanıcı yanıtını işle.

    interrupt_before sonrası resume edildiğinde çalışır.
    Kullanıcının seçtiği opsiyon veya verdiği cevaba göre intent belirlenir.

    Metadata ambiguity (column/value) için kullanıcı cevabını runtime config'e ekler.
    """
    user_response = state.get("user_clarification")
    pending_question = state.get("pending_question")

    if not user_response:
        logger.warning("[REPORT] No user clarification found")
        return {}

    logger.info(f"[REPORT] Processing clarification: {user_response}")

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
    """
    user_query = get_last_user_message(state)

    if not user_query:
        logger.error("[REPORT] No user message found")
        return {"error": "No user message found"}

    logger.info(f"[REPORT] Extracted query: {user_query[:100]}...")

    # Set user_query for merged Text2SQL nodes
    return {"user_query": user_query}


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
        "query_history": [new_checkpoint]
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
        """
        text2sql_output = state.get("text2sql_output")
        viz_decision = state.get("_viz_decision")

        if not text2sql_output:
            return {"error": "No text2sql output", "visualization_output": None}

        if text2sql_output.get("error"):
            return {
                "error": f"Cannot visualize: {text2sql_output['error']}",
                "visualization_output": None
            }

        # Check if graph is needed
        if viz_decision and not viz_decision.get("needs_graph"):
            logger.info(f"[REPORT] No graph needed: {viz_decision.get('reason')}")
            # Return formatted output without calling visualization graph
            output_type = viz_decision.get("output_type", "table")
            results = text2sql_output.get("results", [])

            formatted_output = {
                "summary": viz_decision.get("reason", "Sonuçlar hazır"),
                "output_type": output_type,
                "needs_graph": False,
                "data": results,
                "sql_query": text2sql_output.get("sql_query"),
                "metadata": text2sql_output.get("metadata", {})
            }

            return {
                "visualization_output": formatted_output,
                "error": None
            }

        logger.info("[REPORT] Invoking visualization graph (render only)...")

        try:
            # Prepare input with decision
            viz_input = {
                **text2sql_output,
                # Pass decision to visualization graph
                "_viz_decision": viz_decision
            }

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

    Visualization output'u formatla ve kullanıcıya gönder.
    """
    viz_output = state.get("visualization_output")
    error = state.get("error")
    no_records = state.get("no_records_message")
    active_context = state.get("active_query_context")

    # Boş sonuç mesajı
    if no_records:
        return {"messages": [AIMessage(content=f"ℹ️ {no_records}")]}

    # Hata mesajı
    if error:
        return {"messages": [AIMessage(content=f"❌ Hata: {error}")]}

    # Visualization yok - check if we have viz_decision and results
    if not viz_output:
        viz_decision = state.get("_viz_decision")

        # For merged mode: results are directly in state
        # For backward compatibility: check text2sql_output
        results = state.get("results")
        text2sql_output = state.get("text2sql_output")

        # Get results from either merged mode or backward compatibility mode
        if results:
            data_results = results
        elif text2sql_output:
            data_results = text2sql_output.get("results", [])
        else:
            data_results = []

        # If we have viz_decision (needs_graph=false case), create output
        if viz_decision and data_results:
            viz_final = {
                "summary": viz_decision.get("reason", "Sonuçlar hazır"),
                "output_type": viz_decision.get("output_type", "table"),
                "needs_graph": False,
                "data": data_results
            }
        else:
            return {"messages": [AIMessage(content="⚠️ Görselleştirme çıktısı bulunamadı")]}
    else:
        # Response oluştur
        viz_final = viz_output.get("visualization_output", {})

    summary = viz_final.get("summary", "Rapor hazır")
    output_type = viz_final.get("output_type", "table")
    needs_graph = viz_final.get("needs_graph", False)
    data = viz_final.get("data", [])

    parts = []

    # Eğer grafik yoksa ama data varsa, direkt sonuçları göster
    if not needs_graph and data:
        # Format data based on output_type
        if output_type == "single_value":
            # Single value - direkt göster, başlık yok
            if data and len(data) > 0:
                value = list(data[0].values())[0] if data[0] else "N/A"
                parts.append(f"📊 **Sonuç:** {value}")
        elif output_type in ["simple_list", "table"]:
            # List or table - başlık ile göster
            parts.append(f"📊 **Sonuçlar** ({len(data)} kayıt):\n")

            # Show all rows (up to 50)
            for i, row in enumerate(data[:50], 1):
                row_str = " | ".join([f"**{k}:** {v}" for k, v in row.items()])
                parts.append(f"{i}. {row_str}")

            if len(data) > 50:
                parts.append(f"\n... ve {len(data) - 50} kayıt daha")
    else:
        # Fallback: eski format
        parts = [
            "📊 Rapor Sonucu:",
            f"• Tip: {output_type}",
            f"• Veri: {len(data)} satır",
            f"• {summary}"
        ]

    # Plotly HTML ekle
    plotly_html = viz_output.get("plotly_html_snippet") if viz_output else None
    if plotly_html and needs_graph:
        import base64
        html_full = f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0">{plotly_html}</body></html>'''
        html_b64 = base64.b64encode(html_full.encode('utf-8')).decode('ascii')
        iframe = f'<iframe src="data:text/html;charset=utf-8;base64,{html_b64}" width="100%" height="500" frameborder="0"></iframe>'
        parts.append(f"\n📈 Grafik:\n{iframe}")

    return {"messages": [AIMessage(content="\n".join(parts))]}


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
        logger.info("[REPORT] Routing to process_query (retry with user clarification)")
        return "process_query"

    # new_query, modify_filter, modify_aggregation, modify_order, modify_columns
    # hepsi process_query'ye gidiyor (text2sql ile işlenecek)
    logger.info(f"[REPORT] Routing to process_query (intent: {intent_type})")
    return "process_query"


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
                return create_clarification_request(
                    question=intent.clarification_question or "Lütfen açıklayın:",
                    options=intent.clarification_options or ["Devam et", "İptal"],
                    context=f"Intent: {intent.intent_type.value}"
                )

            # Return enhanced intent info
            return {
                "_intent_type": intent.intent_type.value,
                "_confidence": intent.confidence,
                "_extracted_entities": intent.extracted_entities,
                "_intent_reasoning": intent.reasoning  # NEW: LLM reasoning trace
            }

        except Exception as e:
            logger.error(f"[REPORT] [LLM] Intent understanding error: {e}")
            # Fallback to simple classification
            return {
                "_intent_type": "new_query",
                "_confidence": 0.5,
                "_extracted_entities": {},
                "_intent_reasoning": f"Error: {e}"
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
