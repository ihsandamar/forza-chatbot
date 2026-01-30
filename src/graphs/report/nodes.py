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

    # Tablo adını config'den veya schema_metadata'dan al
    table_name = ""
    schema_metadata = text2sql_output.get("schema_metadata", {})
    if schema_metadata:
        # İlk key'i tablo adı olarak kullan (basit yaklaşım)
        table_name = "MasterReportDocumentTable"  # Default

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


def create_intent_classifier_node(llm: BaseChatModel):
    """
    Intent classifier node factory.

    Args:
        llm: Language model for classification

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

        Önce simple classifier dener, belirsizse LLM classifier kullanır.
        """
        user_message = get_last_user_message(state)
        if not user_message:
            return {"error": "No user message found"}

        logger.info(f"[REPORT] Classifying intent: {user_message[:50]}...")

        active_context = state.get("active_query_context")
        has_context = active_context is not None

        # Önce simple classifier dene (hızlı)
        simple_result = simple_classifier.classify(user_message, has_context)

        # Confidence yeterli değilse LLM classifier kullan
        if simple_result.confidence < 0.6:
            logger.info("[REPORT] Low confidence, using LLM classifier")
            messages = state.get("messages", [])
            classification = await llm_classifier.classify(
                user_message, messages, active_context
            )
        else:
            classification = simple_result
            logger.info(f"[REPORT] Simple classifier sufficient: {classification.intent_type}")

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
    """
    user_response = state.get("user_clarification")
    pending_question = state.get("pending_question")

    if not user_response:
        logger.warning("[REPORT] No user clarification found")
        return {}

    logger.info(f"[REPORT] Processing clarification: {user_response}")

    # Yanıta göre intent'i belirle
    response_lower = user_response.lower()

    if "yeni" in response_lower or "oluştur" in response_lower:
        intent_type = IntentType.NEW_QUERY
    elif "değiştir" in response_lower or "filtre" in response_lower:
        intent_type = IntentType.MODIFY_FILTER
    elif "geri" in response_lower or "önceki" in response_lower:
        intent_type = IntentType.ROLLBACK
    else:
        intent_type = IntentType.NEW_QUERY  # Default

    return {
        "_intent_type": intent_type.value,
        "pending_question": None,
        "waiting_for_user_input": False,
        "user_clarification": None
    }


async def extract_query_node(state: ReportState) -> Dict[str, Any]:
    """
    Kullanıcı sorgusunu çıkar ve doğrula.

    Messages'dan son HumanMessage'ı alır.
    """
    user_query = get_last_user_message(state)

    if not user_query:
        logger.error("[REPORT] No user message found")
        return {"error": "No user message found"}

    logger.info(f"[REPORT] Extracted query: {user_query[:100]}...")
    return {}


async def check_results_node(state: ReportState) -> Dict[str, Any]:
    """
    Text2SQL sonuçlarını kontrol et.

    Boş sonuç varsa HITL sorusu sor.
    """
    text2sql_output = state.get("text2sql_output")

    if not text2sql_output:
        return {"error": "No text2sql output"}

    results = text2sql_output.get("results", [])
    logger.info(f"[REPORT] Checking results: {len(results)} rows")

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
    updated_context = update_active_context(active_context, text2sql_output)

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

    Args:
        text2sql_graph: Compiled text2sql graph

    Returns:
        Node function
    """
    from langchain_core.runnables import RunnableConfig

    async def text2sql_node(state: ReportState, config: RunnableConfig = None) -> Dict[str, Any]:
        """Text2SQL graph'ı çağır with runtime config."""
        user_query = get_last_user_message(state)

        if not user_query:
            return {"error": "No user query found", "text2sql_output": None}

        logger.info("[REPORT] Invoking text2sql graph...")

        try:
            # Context bilgisini ekle (delta-SQL için)
            active_context = state.get("active_query_context")

            text2sql_input = {
                "user_query": user_query,
                "parsed_intent": None,
                "enriched_metadata": None,
                "resolved_steps": None,
                "resolution_metadata": None,
                "sql_queries": None,
                "results": None,
                "final_response": None,
                "error": None
            }

            # Context varsa ekle (ileride delta-SQL için kullanılacak)
            if active_context:
                text2sql_input["_previous_context"] = active_context

            # Pass runtime config to text2sql graph
            # This allows runtime configuration from supervisor/report to reach text2sql
            logger.debug(f"[REPORT] Passing config to text2sql: {config is not None}")
            result = await text2sql_graph.ainvoke(text2sql_input, config)

            logger.info(f"[REPORT] Text2SQL completed: {len(result.get('results', []))} rows")

            return {
                "text2sql_output": result,
                "error": result.get("error")
            }

        except Exception as e:
            logger.error(f"[REPORT] Text2SQL error: {e}", exc_info=True)
            return {"error": f"Text2SQL error: {e}", "text2sql_output": None}

    return text2sql_node


def create_visualization_node(visualization_graph):
    """
    Visualization node factory.

    Args:
        visualization_graph: Compiled visualization graph

    Returns:
        Node function
    """
    from langchain_core.runnables import RunnableConfig

    async def visualization_node(state: ReportState, config: RunnableConfig = None) -> Dict[str, Any]:
        """Visualization graph'ı çağır with runtime config."""
        text2sql_output = state.get("text2sql_output")

        if not text2sql_output:
            return {"error": "No text2sql output", "visualization_output": None}

        if text2sql_output.get("error"):
            return {
                "error": f"Cannot visualize: {text2sql_output['error']}",
                "visualization_output": None
            }

        logger.info("[REPORT] Invoking visualization graph...")

        try:
            # Pass runtime config to visualization graph
            result = await visualization_graph.ainvoke(text2sql_output, config)
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

    # Visualization yok
    if not viz_output:
        return {"messages": [AIMessage(content="⚠️ Görselleştirme çıktısı bulunamadı")]}

    # Response oluştur
    viz_final = viz_output.get("visualization_output", {})
    summary = viz_final.get("summary", "Rapor hazır")
    output_type = viz_final.get("output_type", "table")
    needs_graph = viz_final.get("needs_graph", False)
    data = viz_final.get("data", [])

    parts = [
        "📊 Rapor Sonucu:",
        f"• Tip: {output_type}",
        f"• Veri: {len(data)} satır",
        f"• {summary}"
    ]

    # Context bilgisi ekle
    if active_context:
        parts.append(f"\n💾 Sorgu kaydedildi (v{len(state.get('query_history', []))})")

    # Plotly HTML ekle
    plotly_html = viz_output.get("plotly_html_snippet")
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

def route_after_intent(state: ReportState) -> str:
    """
    Intent classification sonrası routing.

    Returns:
        Next node name
    """
    # HITL bekliyor mu?
    if state.get("waiting_for_user_input"):
        return "ask_user"

    # Intent type'a göre route et
    intent_type = state.get("_intent_type", "new_query")

    if intent_type == "rollback":
        return "rollback"

    # Default: process_query
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

    return "visualization"
