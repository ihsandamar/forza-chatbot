import json
import logging
import re
from typing import Callable, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from src.graphs.report_agent.prompts import (
    EntityExtractionResult,
    IntentClassificationResult,
    QueryClarificationResult,
    SqlModificationResult,
    ENTITY_EXTRACTOR_PROMPT,
    INTENT_CLASSIFIER_PROMPT,
    QUERY_CLARIFICATION_PROMPT,
    SQL_MODIFIER_PROMPT,
)

logger = logging.getLogger(__name__)

# Post-processing: [DocumentDate] =/BETWEEN 'YYYY-...' → CAST([DocumentDate] AS DATE) ...
_DATE_EQ_RE = re.compile(
    r"\[DocumentDate\]\s*(=|BETWEEN)",
    re.IGNORECASE,
)

CONFIDENCE_THRESHOLD = 0.70
MODIFY_AMBIGUITY_THRESHOLD = 0.85  # MODIFY_QUERY için ayrı eşik — daha yüksek güven gerekir

# ---------------------------------------------------------------------------
# Chart type keyword detection — deterministic fallback for LLM structured output.
#
# LLM with structured Literal fields can return None for typos like "sunbrust".
# This pure function covers that gap without touching the LLM call.
#
# Design: bare English single-words ("bar", "line", "pie") intentionally excluded
# — they are collision-prone substrings in Turkish text (e.g. "kabartma" contains
# "bar"). Only compound English forms and clearly chart-specific Turkish keywords
# are included.
# ---------------------------------------------------------------------------
_CHART_KEYWORD_MAP: dict[str, str] = {
    # sunburst — includes the common typo that triggered this fix
    "sunburst": "sunburst",
    "sunbrust": "sunburst",
    # heatmap
    "heatmap": "heatmap",
    "ısıharitası": "heatmap",   # Turkish: "ısı haritası" → stripped spaces
    # treemap
    "treemap": "treemap",
    # bar chart — compound only (bare "bar" is a collision risk in Turkish)
    "barchart": "bar_chart",
    "çubuk": "bar_chart",
    "cubuk": "bar_chart",
    # line chart — compound only
    "linechart": "line_chart",
    "çizgi": "line_chart",
    "cizgi": "line_chart",
    # pie chart — compound only
    "piechart": "pie_chart",
    "pasta": "pie_chart",
    # scatter chart — compound only
    "scatterchart": "scatter_chart",
}


def _detect_chart_type_from_query(text: str) -> Optional[str]:
    """Deterministic chart type extraction from user query text.

    Normalizes input (lowercase, collapse whitespace/hyphens/underscores) then
    checks for substrings against _CHART_KEYWORD_MAP.

    Returns canonical chart type string (e.g. "sunburst") or None if no keyword found.
    Pure function — no LLM, no I/O, safe to call from any context.
    """
    if not text or not text.strip():
        return None
    # Normalize: lowercase, strip whitespace/separators (keep Turkish chars like ı, ş, ç)
    normalized = re.sub(r"[\s_\-]", "", text.lower())
    for keyword, chart_type in _CHART_KEYWORD_MAP.items():
        if keyword in normalized:
            return chart_type
    return None


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

        # --- Table refresh detection (before LLM call) ---
        _REFRESH_KEYWORDS = {"verileri güncelle", "tabloyu güncelle", "verileri yenile", "tabloyu yenile", "veriyi güncelle", "veriyi yenile"}
        user_lower = user_query.lower().strip()
        is_refresh_request = any(kw in user_lower for kw in _REFRESH_KEYWORDS)

        if is_refresh_request:
            logger.info(f"[CLASSIFY] Table refresh detected: '{user_query}'")
            return {
                "user_query": user_query,
                "intent_type": "NEW_QUERY",
                "query_type": "SINGLE",
                "intent_confidence": 1.0,
                "wants_visualization": False,
                "requested_chart_type": None,
                "use_result_type": None,
                "compute_operation": None,
                "visualization_output": None,
                "pre_built_sql": None,
                "modification_hints": None,
                "_force_table_refresh": True,
            }

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

        # Post-LLM fallback: LLM structured output typo/edge-case'lerde
        # requested_chart_type=None döndürebilir (non-deterministic, OpenAI backend-dependent).
        # Kullanıcı vizualizasyon istiyorsa ve LLM chart type'ı çözemediyse,
        # deterministic keyword lookup ile override et.
        # revisualize path'ini de kapsar (nodes.py wants_viz hesabını yansıtır).
        _wants_viz_effective = result.wants_visualization or (result.use_result_type == "revisualize")
        if _wants_viz_effective and result.requested_chart_type is None:
            _detected = _detect_chart_type_from_query(user_query)
            if _detected:
                result = result.model_copy(update={"requested_chart_type": _detected})
                logger.info(
                    f"[CLASSIFY] Fallback chart type detected: '{_detected}' from query"
                )

        logger.info(
            f"[CLASSIFY] {result.intent_type}/{result.query_type} "
            f"conf={result.confidence:.2f} wants_viz={result.wants_visualization}"
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

        # revisualize her zaman görselleştirme talebidir
        wants_viz = result.wants_visualization or (result.use_result_type == "revisualize")

        # revisualize'da user_query SQL semantic query'yi kirletmemesi için
        # viz_request ayrı bir alana yazılır; diğer pathlerde None (reset).
        is_revisualize = result.use_result_type == "revisualize"
        return_dict = {
            "user_query": user_query,   # downstream SQL node'lar (term_resolver, sql_architect) okur
            "viz_request": user_query if is_revisualize else None,  # viz_decider'ın özel alanı
            "intent_type": result.intent_type,
            "query_type": result.query_type,
            "intent_confidence": result.confidence,
            "wants_visualization": wants_viz,
            "requested_chart_type": result.requested_chart_type,
            "use_result_type": result.use_result_type,
            "compute_operation": result.compute_operation,  # compute path için (avg/sum/count/min/max)
            "visualization_output": None,  # önceki tur çıktısını temizle
            "pre_built_sql": None,          # her turda temizle — yeni tur için geçersiz kıl
            "time_granularity": None,       # her turda temizle — stale state önle
            "modification_hints": None,   # her turda temizle
            "_force_table_refresh": False,
            "_clarification_count": 0 if result.intent_type != "VAGUE_QUERY" else state.get("_clarification_count", 0),
            "_skip_vague_check": False,
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

        # Sonuçların ilk 5 satırını al (token limiti için)
        active_results = state.get("active_results") or []
        results_preview = json.dumps(
            active_results[:5], ensure_ascii=False, default=str
        ) if active_results else "Sonuç yok"

        # Konuşma geçmişi: zamir referanslarını ("bu ürün", "o şube") çözmek için
        # Son 6 mesajı al (modification_request ile çakışma zararsız)
        messages = state.get("messages") or []
        context_lines: list[str] = []
        for msg in messages[-6:]:
            if isinstance(msg, HumanMessage):
                role = "Kullanıcı"
            elif isinstance(msg, AIMessage):
                role = "Asistan"
            else:
                continue
            content = msg.content[:200] if msg.content else ""
            context_lines.append(f"{role}: {content}")
        conversation_context = "\n".join(context_lines) if context_lines else "Yok"

        prompt = SQL_MODIFIER_PROMPT.format(
            active_sql=active_sql,
            active_filters=json.dumps(state.get("active_filters") or [], ensure_ascii=False),
            active_results=results_preview,
            modification_request=state.get("user_query", ""),
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
            conversation_context=conversation_context,
        )

        result: SqlModificationResult = await structured_llm.ainvoke(prompt)

        logger.info(
            f"[MODIFY_SQL] confidence={result.confidence:.2f} "
            f"explanation={result.explanation[:80]}"
        )

        # Düşük güven: kullanıcıya sor
        if result.confidence < 0.5:
            logger.warning(
                f"[MODIFY_SQL] Low confidence ({result.confidence:.2f}), "
                f"interrupting user"
            )
            answer = interrupt({
                "type": "clarification",
                "question": (
                    f"İsteğinizi tam anlayamadım: \"{state.get('user_query', '')}\"\n"
                    f"Şu şekilde anladım: {result.explanation}\n"
                    "Doğru mu, yoksa daha açık belirtir misiniz?"
                ),
            })
            # Kullanıcı açıklama yaptıysa yeni query olarak tekrar dene
            if answer and isinstance(answer, str) and answer.strip():
                return {
                    "user_query": answer.strip(),
                    "intent_type": "MODIFY_QUERY",
                }

        # Post-processing: datetime kolon güvenlik ağı
        # [DocumentDate] = '...' → CAST([DocumentDate] AS DATE) = '...'
        modified_sql = _DATE_EQ_RE.sub(
            lambda m: f"CAST([DocumentDate] AS DATE) {m.group(1)}",
            result.modified_sql,
        )
        if modified_sql != result.modified_sql:
            logger.info("[MODIFY_SQL] DocumentDate CAST post-processing uygulandı")

        logger.info(f"[MODIFY_SQL] → {modified_sql[:120]}")
        logger.info(f"[MODIFY_SQL] {len(result.modification_hints)} hint(s) üretildi")
        # pre_built_sql: sql_generator bu alanı görünce yeniden SQL üretmez,
        # direkt bu SQL'i kullanır (CategoryName filtresi, doğru aggregation kolonları korunur).
        return {
            "pre_built_sql": modified_sql,
            "modification_hints": [h.model_dump() for h in result.modification_hints],
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
        logger.info(f"[EXTRACT_ENTITY] {result.entity_name} ({result.entity_type})")

        if state.get("use_result_type") == "modify_context":
            # modify_sql_node'a gidecek: entity adını orijinal sorguya inject et
            original_query = state.get("user_query", "")
            enriched = f"{result.entity_name} için: {original_query}"
            logger.info(f"[EXTRACT_ENTITY] modify_context → enriched query: {enriched[:80]}")
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


async def build_response_node(state: dict) -> dict:
    """Final Response Builder: pure Python, LLM yok."""
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
        import base64

        html_snippet = viz["plotly_html_snippet"]
        summary = viz.get("summary", "Grafiğiniz oluşturuldu.")
        chart_type = viz.get("chart_type", "chart")
        row_count = len(results)

        # Wrap div snippet in full HTML document
        full_html = (
            '<!DOCTYPE html>\n<html>\n<head>\n'
            '    <meta charset="UTF-8">\n'
            '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            '</head>\n<body style="margin:0;padding:0;">\n'
            f'{html_snippet}\n'
            '</body>\n</html>'
        )
        b64 = base64.b64encode(full_html.encode("utf-8")).decode("utf-8")
        iframe = (
            f'<iframe src="data:text/html;charset=utf-8;base64,{b64}" '
            f'style="width:100%;height:100vh;border:none;"></iframe>'
        )

        # SHORT summary for LLM context (no base64 bloat)
        summary_text = (
            f"\U0001f4ca Rapor Sonucu:\n"
            f"\u2022 Görselleştirme Tipi: {chart_type}\n"
            f"\u2022 Grafik Gerekli: \u2713 Evet\n"
            f"\u2022 Veri Noktası: {row_count}\n"
            f"\u2022 {row_count} kayıt\n"
            f"### \U0001f4c8 Grafik oluşturuldu."
        )

        # Full response with iframe for user display
        full_response = f"{summary_text}\n\n{iframe}"

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
