import json
import logging
from typing import Callable, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from src.graphs.report_agent.prompts import (
    EntityExtractionResult,
    FilterDelta,
    IntentClassificationResult,
    QueryClarificationResult,
    SqlDelta,
    ENTITY_EXTRACTOR_PROMPT,
    INTENT_CLASSIFIER_PROMPT,
    QUERY_CLARIFICATION_PROMPT,
    SQL_MODIFIER_PROMPT,
)

from src.graphs.report_agent.response_builder import build_chart_response, DEFAULT_CONFIG

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.70
MODIFY_AMBIGUITY_THRESHOLD = 0.85  # MODIFY_QUERY için ayrı eşik — daha yüksek güven gerekir


def create_classify_intent_node(llm) -> Callable:
    """Intent Classifier: user_query → intent_type + query_type.
    Confidence < 0.70 ise interrupt() ile kullanıcıya sorar.
    """
    structured_llm = llm.with_structured_output(IntentClassificationResult)

    async def classify_intent_node(state: dict) -> dict:
        logger.info(f"[REPORT_AGENT] ===== classify_intent_node ENTERED ===== query: {state.get('messages', [{}])[-1].content[:80] if state.get('messages') else 'NO_MESSAGES'}")
        active_sql = state.get("active_sql")
        active_results = state.get("active_results") or []
        messages = state.get("messages", [])

        # Her zaman messages'taki son HumanMessage'ı kullan (multi-turn desteği).
        # state.get("user_query") önceki turdan kalan bayat değer olabilir.
        human_msgs = [
            m for m in messages
            if isinstance(m, HumanMessage) and m.content and isinstance(m.content, str) and m.content.strip()
        ]
        if human_msgs:
            user_query = human_msgs[-1].content.strip()
            extracted_from_messages = True
            logger.info(f"[CLASSIFY] user_query from latest message: {user_query[:80]}")
        else:
            # Fallback: doğrudan user_query set edilmiş (API/test senaryosu)
            user_query = state.get("user_query", "")
            extracted_from_messages = False

        history_parts = []
        for msg in messages[-6:]:
            if isinstance(msg, HumanMessage):
                history_parts.append(f"Kullanıcı: {msg.content[:400]}")
            elif isinstance(msg, AIMessage):
                history_parts.append(f"Asistan: {msg.content[:400]}")

        prompt = INTENT_CLASSIFIER_PROMPT.format(
            user_query=user_query,
            conversation_history="\n".join(history_parts) or "İlk mesaj",
            has_active_sql="Evet" if active_sql else "Hayır",
            result_count=len(active_results),
        )

        result: IntentClassificationResult = await structured_llm.ainvoke(prompt)

        logger.info(
            f"[CLASSIFY] {result.intent_type}/{result.query_type} "
            f"conf={result.confidence:.2f} wants_viz={result.wants_visualization} "
            f"time_breakdown={result.time_breakdown}"
        )

        # Max clarification tur aşıldıysa VAGUE_QUERY'yi NEW_QUERY'ye zorla
        if result.intent_type == "VAGUE_QUERY" and state.get("_skip_vague_check"):
            logger.info("[CLASSIFY] _skip_vague_check active, overriding VAGUE_QUERY → NEW_QUERY")
            result.intent_type = "NEW_QUERY"

        # Genel güven eşiği — tüm intent'ler için
        needs_clarification = result.confidence < CONFIDENCE_THRESHOLD

        # MODIFY_QUERY için ek kontrol: devam eden sorgu mu, yeni mi? daha yüksek güven gerekir
        if (
            not needs_clarification
            and result.intent_type == "MODIFY_QUERY"
            and active_sql
            and result.confidence < MODIFY_AMBIGUITY_THRESHOLD
        ):
            needs_clarification = True
            logger.info(
                f"[CLASSIFY] MODIFY_QUERY ambiguity check triggered "
                f"(conf={result.confidence:.2f} < {MODIFY_AMBIGUITY_THRESHOLD})"
            )

        if needs_clarification:
            options = ["Yeni sorgu yap"]
            if active_sql:
                options.append("Mevcut sorguyu değiştir")
            options.append("Sonuçları farklı göster")

            answer = interrupt({
                "type": "choice",
                "question": f"'{user_query}' için ne yapmamı istiyorsunuz?",
                "options": options,
            })
            result = _resolve_intent_from_answer(result, answer)

        # revisualize her zaman görselleştirme talebidir.
        wants_viz = (
            result.wants_visualization
            or (result.use_result_type == "revisualize")
        )

        chart_type = result.chart_type
        chart_x_hint = result.chart_x_hint

        if chart_type:
            logger.info(f"[CLASSIFY] chart_type={chart_type}, chart_x_hint={chart_x_hint}")

        is_revisualize = result.use_result_type == "revisualize"
        return_dict = {
            "user_query": user_query,
            "viz_request": user_query if is_revisualize else None,
            "intent_type": result.intent_type,
            "query_type": result.query_type,
            "intent_confidence": result.confidence,
            "wants_visualization": wants_viz,
            "requested_chart_type": chart_type,
            "chart_x_hint": chart_x_hint,
            "use_result_type": result.use_result_type,
            "compute_operation": result.compute_operation,
            "visualization_output": None,
            "pre_built_sql": None,
            "time_granularity": None,
            "time_breakdown": result.time_breakdown,
            "modification_hints": None,
            "semantic_intent": None,
            "term_resolution": None,
            "_clarification_count": 0 if result.intent_type != "VAGUE_QUERY" else state.get("_clarification_count", 0),
            "_skip_vague_check": False,
            "text2sql_clarification": None,
            "text2sql_answers": None,
            "_hitl_answered": False,
            "accumulated_entities": state.get("accumulated_entities"),
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
    """SQL Modifier: active_sql + SqlDelta → modified_sql via SqlDeltaApplicator."""
    from src.graphs.report_agent.context_builder import build_query_context_summary
    from src.graphs.report_agent.subagents.text2sql.sql_delta import SqlDeltaApplicator

    structured_llm = llm.with_structured_output(SqlDelta)

    async def modify_sql_node(state: dict) -> dict:
        active_sql = state.get("active_sql", "")
        if not active_sql:
            logger.warning("[MODIFY_SQL] No active SQL, fallback to NEW_QUERY")
            return {"intent_type": "NEW_QUERY"}

        query_context = build_query_context_summary(
            state.get("active_results"),
            state.get("active_filters"),
            state.get("accumulated_entities"),
        )

        prompt = SQL_MODIFIER_PROMPT.format(
            active_sql=active_sql,
            query_context=query_context,
            modification_request=state.get("user_query", ""),
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
        )

        delta: SqlDelta = await structured_llm.ainvoke(prompt)

        logger.info(
            f"[MODIFY_SQL] confidence={delta.confidence:.2f} "
            f"explanation={delta.explanation[:80]}"
        )

        if delta.confidence < 0.5:
            logger.warning(
                f"[MODIFY_SQL] Low confidence ({delta.confidence:.2f}), interrupting user"
            )
            answer = interrupt({
                "type": "clarification",
                "question": (
                    f"İsteğinizi tam anlayamadım: \"{state.get('user_query', '')}\"\n"
                    f"Şu şekilde anladım: {delta.explanation}\n"
                    "Doğru mu, yoksa daha açık belirtir misiniz?"
                ),
            })
            if answer and isinstance(answer, str) and answer.strip():
                return {
                    "user_query": answer.strip(),
                    "intent_type": "MODIFY_QUERY",
                }

        modified_sql = SqlDeltaApplicator().apply(active_sql, delta)
        logger.info(f"[MODIFY_SQL] → {modified_sql[:120]}")

        modification_hints = [
            {"column": f.column, "embedded_value": f.value.strip("'")}
            for f in delta.add_filters
            if f.operator == "="
        ]
        logger.info(f"[MODIFY_SQL] {len(modification_hints)} hint(s) üretildi")

        return {
            "pre_built_sql": modified_sql,
            "modification_hints": modification_hints,
        }

    return modify_sql_node


MAX_CLARIFICATION_TURNS = 2


def create_report_chat_node(llm, column_metadata: dict) -> Callable:
    """Report Chat: VAGUE_QUERY → kullanıcıya öneriler sun, cevabı user_query olarak set et."""
    structured_llm = llm.with_structured_output(QueryClarificationResult)

    async def report_chat_node(state: dict) -> dict:
        count = (state.get("_clarification_count") or 0) + 1

        # Sonsuz döngü koruması: max tura ulaştıysa en iyi tahminle devam et
        if count > MAX_CLARIFICATION_TURNS:
            logger.warning(
                f"[REPORT_CHAT] Max clarification turns ({MAX_CLARIFICATION_TURNS}) "
                f"reached, proceeding with original query as NEW_QUERY"
            )
            return {
                "_clarification_count": 0,
                "_skip_vague_check": True,
            }

        prompt = QUERY_CLARIFICATION_PROMPT.format(
            user_query=state.get("user_query", ""),
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
        )

        result: QueryClarificationResult = await structured_llm.ainvoke(prompt)
        logger.info(
            f"[REPORT_CHAT] {len(result.suggestions)} suggestions generated "
            f"(turn {count}/{MAX_CLARIFICATION_TURNS})"
        )

        # interrupt() ile kullanıcıya hibrit seçenek sun
        answer = interrupt({
            "type": "clarification",
            "question": result.message,
            "options": result.suggestions,
        })

        # Kullanıcı bir seçenek seçtiyse veya serbest metin yazdıysa
        chosen_query = answer.strip() if isinstance(answer, str) and answer.strip() else state.get("user_query", "")
        logger.info(f"[REPORT_CHAT] User chose: {chosen_query[:80]}")

        return {
            "user_query": chosen_query,
            "messages": [HumanMessage(content=chosen_query)],
            "_clarification_count": count,
        }

    return report_chat_node


def create_extract_entity_node(llm) -> Callable:
    """Entity Extractor: USE_RESULT(new_query/modify_context) → yeni user_query seed'i veya enriched query."""
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
        logger.info(f"[EXTRACT_ENTITY] {result.entity_names} ({result.entity_type})")

        if state.get("use_result_type") == "modify_context":
            # modify_sql_node'a gidecek: entity adlarini orijinal sorguya inject et
            names_str = ", ".join(result.entity_names)
            original_query = state.get("user_query", "")
            enriched = f"{names_str} icin: {original_query}"
            logger.info(f"[EXTRACT_ENTITY] modify_context -> enriched query: {enriched[:80]}")
            return {"user_query": enriched}

        return {"user_query": result.new_query_seed}

    return extract_entity_node


# =============================================================================
# COMPUTE LABELS (module-level sabit)
# =============================================================================
_COMPUTE_OP_LABELS = {
    "sum":   "Toplam",
    "avg":   "Ortalama",
    "count": "Adet",
    "min":   "Minimum",
    "max":   "Maksimum",
}


def _execute_compute_tool(
    results: list[dict],
    tool: str,
    target_column: str,
    display_columns: list[str],
) -> dict:
    """
    Pure Python tool execution. Returns:
      {"value": <computed>, "row": <full_row_or_None>, "display": {col: val}}
    """
    values = [
        (i, row[target_column])
        for i, row in enumerate(results)
        if target_column in row
        and row[target_column] is not None
        and isinstance(row[target_column], (int, float))
    ]

    if not values and tool != "count_rows":
        return {"value": None, "row": None, "display": {}}

    if tool == "find_max":
        idx, val = max(values, key=lambda x: x[1])
        row = results[idx]
        display = {c: row.get(c) for c in display_columns}
        return {"value": val, "row": row, "display": display}

    elif tool == "find_min":
        idx, val = min(values, key=lambda x: x[1])
        row = results[idx]
        display = {c: row.get(c) for c in display_columns}
        return {"value": val, "row": row, "display": display}

    elif tool == "sum_column":
        total = sum(v for _, v in values)
        return {"value": total, "row": None, "display": {target_column: total}}

    elif tool == "avg_column":
        avg = sum(v for _, v in values) / len(values)
        return {"value": avg, "row": None, "display": {target_column: avg}}

    elif tool == "count_rows":
        count = len(results)
        return {"value": count, "row": None, "display": {"count": count}}

    return {"value": None, "row": None, "display": {}}


def _format_compute_result(tool: str, tool_result: dict, display_columns: list[str]) -> str:
    """Tool sonucunu insan-okunabilir formata çevir."""
    val = tool_result["value"]
    if val is None:
        return "Hesaplama yapılamadı."

    if tool in ("find_max", "find_min"):
        label = "En yüksek" if tool == "find_max" else "En düşük"
        row = tool_result["row"] or {}
        text_parts = []
        num_parts = []
        for col in display_columns:
            v = row.get(col)
            if v is None:
                continue
            if isinstance(v, (int, float)):
                num_parts.append(f"{col}: {v:,.2f}")
            else:
                text_parts.append(str(v))

        entity = ", ".join(text_parts) if text_parts else ""
        value_str = " | ".join(num_parts) if num_parts else f"{val:,.2f}"

        if entity:
            return f"{label}: **{entity}** — {value_str}"
        return f"{label}: {value_str}"

    elif tool == "count_rows":
        return f"Toplam satır sayısı: **{val:,}**"

    else:
        op_label = "Toplam" if tool == "sum_column" else "Ortalama"
        formatted = f"{val:,.2f}" if isinstance(val, float) else f"{val:,}"
        return f"{op_label}: **{formatted}**"


def _compute_fallback(results: list[dict], numeric_cols: list[str], operation: str) -> dict:
    """LLM başarısız olursa eski pure-Python davranış."""
    lines = []
    for col in numeric_cols:
        values = [
            row[col] for row in results
            if row.get(col) is not None and isinstance(row.get(col), (int, float))
        ]
        if not values:
            continue

        if operation == "sum":
            computed = sum(values)
        elif operation == "avg":
            computed = sum(values) / len(values)
        elif operation == "count":
            computed = len(values)
        elif operation == "min":
            computed = min(values)
        elif operation == "max":
            computed = max(values)
        else:
            computed = sum(values)

        label = _COMPUTE_OP_LABELS.get(operation, operation.upper())
        formatted = f"{computed:.2f}" if isinstance(computed, float) else f"{computed:,}"
        lines.append(f"**{col}** → {label}: {formatted}")

    response = "\n".join(lines) if lines else "Hesaplama yapılamadı."
    return {"final_response": response, "error": None}


def create_compute_results_node(llm) -> Callable:
    """Hybrid compute node: LLM tool selection + pure Python execution."""

    from src.graphs.report_agent.prompts import ComputeToolSelection, COMPUTE_TOOL_PROMPT
    structured_llm = llm.with_structured_output(ComputeToolSelection)

    async def compute_results_node(state: dict) -> dict:
        results = state.get("active_results") or []

        if not results:
            return {
                "final_response": "Hesaplama için önceki sorgu sonuçları bulunamadı.",
                "error": None,
            }

        # Kolon tipleri
        numeric_cols = [
            col for col in results[0]
            if isinstance(results[0].get(col), (int, float))
            and not isinstance(results[0].get(col), bool)
        ]
        text_cols = [col for col in results[0] if col not in numeric_cols]

        if not numeric_cols:
            return {
                "final_response": "Sonuçlarda sayısal kolon bulunamadı.",
                "error": None,
            }

        # Phase 1: LLM tool selection
        try:
            prompt = COMPUTE_TOOL_PROMPT.format(
                active_results=json.dumps(results[:5], ensure_ascii=False, default=str),
                numeric_columns=", ".join(numeric_cols),
                text_columns=", ".join(text_cols),
                user_query=state.get("user_query", ""),
            )
            selection = await structured_llm.ainvoke(prompt)
            tool = selection.tool
            target = selection.target_column
            display = selection.display_columns
            logger.info(f"[COMPUTE] LLM selected: {tool}({target}) display={display}")
        except Exception as e:
            # Fallback: compute_operation state field'ından eski davranış
            logger.warning(f"[COMPUTE] LLM failed ({e}), falling back to compute_operation")
            op = state.get("compute_operation") or "sum"
            return _compute_fallback(results, numeric_cols, op)

        # Phase 2: Tool execution
        tool_result = _execute_compute_tool(results, tool, target, display)

        # Phase 3: Format
        response = _format_compute_result(tool, tool_result, display)
        logger.info(f"[COMPUTE] Response: {response[:100]}")

        return {"final_response": response, "error": None}

    return compute_results_node


def _results_to_markdown_table(results: list, max_rows: int = 50) -> str:
    """Convert a list of dicts to a markdown table."""
    if not results:
        return "Bu sorgu için sonuç bulunamadı."

    headers = list(results[0].keys())
    header_line = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"

    rows = results[:max_rows]
    row_lines = []
    for row in rows:
        cells = [str(row.get(h, "")) for h in headers]
        row_lines.append("| " + " | ".join(cells) + " |")

    table = "\n".join([header_line, separator] + row_lines)

    remaining = len(results) - max_rows
    if remaining > 0:
        table += f"\n\n*...ve {remaining} satır daha*"

    return table


def create_build_response_node(llm=None):
    """Factory: returns build_response_node with optional LLM for insight generation."""
    async def build_response_node(state: dict) -> dict:
        import base64
        error = state.get("error")
        results = state.get("results") or []
        viz = state.get("visualization_output") or {}

        # compute_results_node kendi final_response'unu zaten ürettiyse kullan.
        # results önceki turdan dolu olsa bile overwrite etme.
        if state.get("use_result_type") == "compute" and state.get("final_response"):
            response = state["final_response"]
        elif error:
            response = f"Sorgu hatası: {error}"
        elif not results:
            response = "Bu sorgu için sonuç bulunamadı."
        elif viz.get("needs_graph") and viz.get("plotly_html_snippet"):
            html_snippet = viz["plotly_html_snippet"]
            chart_type = viz.get("chart_type", "chart")

            inner_html = (
                '<!DOCTYPE html><html><head>'
                '<meta charset="UTF-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
                '<style>'
                'html,body{margin:0;padding:0;height:100%;overflow:hidden;}'
                '.plotly-graph-div{width:100%!important;height:100%!important;}'
                '</style>'
                '</head><body>'
                f'{html_snippet}'
                '</body></html>'
            )
            srcdoc = inner_html.replace('&', '&amp;').replace('"', '&quot;')
            src_b64 = base64.b64encode(inner_html.encode("utf-8")).decode("utf-8")
            height = '600px' if chart_type == 'turkey_map' else '480px'
            iframe = (
                f'<iframe srcdoc="{srcdoc}" '
                f'src="data:text/html;charset=utf-8;base64,{src_b64}" '
                f'style="width:100%;height:{height};border:none;display:block;"></iframe>'
            )

            summary_text = await build_chart_response(
                results, viz, state.get("user_query", ""), DEFAULT_CONFIG, llm
            )

            # Full response with iframe for user display
            full_response = summary_text + "\n\n" + iframe

            # Messages: short summary in content (LLM sees this)
            # chart_html in additional_kwargs (LLM does NOT see this, chat_service extracts it)
            return {
                "final_response": full_response,
                "messages": [AIMessage(
                    content=summary_text,
                    additional_kwargs={"chart_html": iframe},
                )],
            }
        else:
            response = _results_to_markdown_table(results)

        return {
            "final_response": response,
            "messages": [AIMessage(content=response)],
        }
    return build_response_node


async def hitl_check_node(state: dict) -> dict:
    """
    text2sql subgraph'tan gelen clarification sinyalini yakalar.
    Varsa report_agent seviyesinde interrupt() çağırır.
    Bu seviyede MemorySaver checkpointer çalışır — interrupt propagate eder.
    """
    clarification = state.get("text2sql_clarification")

    if not clarification:
        return {"_hitl_answered": False}

    answer = interrupt(clarification)

    answers = list(state.get("text2sql_answers") or [])
    answers.append({"source": clarification["source"], "answer": answer})

    return {
        "text2sql_clarification": None,
        "text2sql_answers": answers,
        "_hitl_answered": True,
    }
