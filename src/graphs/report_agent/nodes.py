import json
import logging
from typing import Callable, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from src.graphs.report_agent.prompts import (
    EntityExtractionResult,
    IntentClassificationResult,
    SqlModificationResult,
    ENTITY_EXTRACTOR_PROMPT,
    INTENT_CLASSIFIER_PROMPT,
    SQL_MODIFIER_PROMPT,
)

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.70


def create_classify_intent_node(llm) -> Callable:
    """Intent Classifier: user_query → intent_type + query_type.
    Confidence < 0.70 ise interrupt() ile kullanıcıya sorar.
    """
    structured_llm = llm.with_structured_output(IntentClassificationResult)

    async def classify_intent_node(state: dict) -> dict:
        user_query = state.get("user_query", "")
        active_sql = state.get("active_sql")
        active_results = state.get("active_results") or []
        messages = state.get("messages", [])

        # user_query boşsa (LangGraph Studio sadece messages gönderdiğinde)
        # son HumanMessage'dan extract et
        extracted_from_messages = False
        if not user_query:
            human_msgs = [
                m for m in messages
                if isinstance(m, HumanMessage) and m.content and m.content.strip()
            ]
            if human_msgs:
                user_query = human_msgs[-1].content.strip()
                extracted_from_messages = True
                logger.info(f"[CLASSIFY] user_query extracted from messages: {user_query[:80]}")

        history_parts = []
        for msg in messages[-4:]:
            if isinstance(msg, HumanMessage):
                history_parts.append(f"Kullanıcı: {msg.content[:100]}")
            elif isinstance(msg, AIMessage):
                history_parts.append(f"Asistan: {msg.content[:100]}")

        prompt = INTENT_CLASSIFIER_PROMPT.format(
            user_query=user_query,
            conversation_history="\n".join(history_parts) or "İlk mesaj",
            has_active_sql="Evet" if active_sql else "Hayır",
            result_count=len(active_results),
        )

        result: IntentClassificationResult = await structured_llm.ainvoke(prompt)
        logger.info(
            f"[CLASSIFY] {result.intent_type}/{result.query_type} "
            f"conf={result.confidence:.2f} wants_viz={result.wants_visualization}"
        )

        if result.confidence < CONFIDENCE_THRESHOLD:
            options = ["Yeni sorgu yap"]
            if active_sql:
                options.append("Mevcut sorguyu değiştir")
            options.append("Sonuçları farklı göster")

            answer = interrupt({
                "type": "confirmation",
                "question": f"'{user_query}' için ne yapmamı istiyorsunuz?",
                "options": options,
            })
            result = _resolve_intent_from_answer(result, answer)

        # revisualize her zaman görselleştirme talebidir
        wants_viz = result.wants_visualization or (result.use_result_type == "revisualize")

        return_dict = {
            "user_query": user_query,   # downstream node'lar (term_resolver, sql_architect) okur
            "intent_type": result.intent_type,
            "query_type": result.query_type,
            "intent_confidence": result.confidence,
            "wants_visualization": wants_viz,
            "use_result_type": result.use_result_type,
        }
        # Mesajı messages'a ekle; messages'tan extract ettiysek zaten orada var
        if not extracted_from_messages and user_query:
            return_dict["messages"] = [HumanMessage(content=user_query)]
        return return_dict

    return classify_intent_node


def _resolve_intent_from_answer(
    result: IntentClassificationResult, answer: str
) -> IntentClassificationResult:
    if "Yeni sorgu" in answer:
        result.intent_type = "NEW_QUERY"
    elif "değiştir" in answer:
        result.intent_type = "MODIFY_QUERY"
    elif "farklı göster" in answer:
        result.intent_type = "USE_RESULT"
        result.use_result_type = "revisualize"
    result.confidence = 1.0
    return result


def create_modify_sql_node(llm, column_metadata: dict) -> Callable:
    """SQL Modifier: active_sql + intent → modified_sql.
    Text2SQL subgraph bypass eder, doğrudan executor'a gider.
    """
    structured_llm = llm.with_structured_output(SqlModificationResult)

    async def modify_sql_node(state: dict) -> dict:
        active_sql = state.get("active_sql", "")
        if not active_sql:
            logger.warning("[MODIFY_SQL] No active SQL, fallback to NEW_QUERY")
            return {"intent_type": "NEW_QUERY"}

        prompt = SQL_MODIFIER_PROMPT.format(
            active_sql=active_sql,
            active_filters=json.dumps(state.get("active_filters") or [], ensure_ascii=False),
            modification_request=state.get("user_query", ""),
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
        )

        result: SqlModificationResult = await structured_llm.ainvoke(prompt)
        logger.info(f"[MODIFY_SQL] → {result.modified_sql[:120]}")
        return {"sql_queries": [result.modified_sql]}

    return modify_sql_node


def create_extract_entity_node(llm) -> Callable:
    """Entity Extractor: USE_RESULT(new_query) → yeni user_query seed'i."""
    structured_llm = llm.with_structured_output(EntityExtractionResult)

    async def extract_entity_node(state: dict) -> dict:
        active_results = state.get("active_results") or []
        if not active_results:
            logger.warning("[EXTRACT_ENTITY] No results, fallback to NEW_QUERY")
            return {"intent_type": "NEW_QUERY"}

        prompt = ENTITY_EXTRACTOR_PROMPT.format(
            active_results=json.dumps(active_results[:5], ensure_ascii=False, indent=2),
            user_query=state.get("user_query", ""),
        )

        result: EntityExtractionResult = await structured_llm.ainvoke(prompt)
        logger.info(f"[EXTRACT_ENTITY] {result.entity_name} ({result.entity_type})")
        return {"user_query": result.new_query_seed}

    return extract_entity_node


async def build_response_node(state: dict) -> dict:
    """Final Response Builder: pure Python, LLM yok."""
    error = state.get("error")
    results = state.get("results") or []
    viz = state.get("visualization_output") or {}

    if error:
        response = f"Sorgu hatası: {error}"
    elif not results:
        response = "Bu sorgu için sonuç bulunamadı."
    elif viz.get("needs_graph") and viz.get("plotly_html_snippet"):
        response = viz["plotly_html_snippet"]
    else:
        response = f"{len(results)} sonuç bulundu."

    return {
        "final_response": response,
        "messages": [AIMessage(content=response)],
    }
