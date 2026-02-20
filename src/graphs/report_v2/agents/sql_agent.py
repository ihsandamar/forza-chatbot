"""
SQLAgent — Report V2

Text-to-SQL pipeline agent. Migrated from src/graphs/report/nodes.py.
Uses the existing generic_text2sql pipeline unchanged, sequential execution.

Pipeline:
    START
      → extract_and_prepare       (enrich query with conversation context, set _sql_context_hint)
      → build_query_type_context  (query-type specific SQL hints)
      → detect_execution_mode     (sets _execution_mode: "full" | "delta")
      → [conditional]
          "delta" → delta_sql_modifier
                       → [conditional]
                           _delta_fallback=True  → create_table  (full pipeline)
                           _delta_fallback=False → sql_executor  (skip heavy nodes)
          "full" / other → create_table
                               → sql_architect
                               → retrieve_business_rules
                               → metadata_enrichment
                               → value_resolver
                               → sql_query_builder
                               → sql_executor
      → update_history
      → build_sql_result
      → END
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from src.graphs.report.state import ActiveQueryContext
from src.graphs.report_v2.state import SQLResult, OrchestratorState, ClassifyResult

logger = logging.getLogger(__name__)


# =============================================================================
# SQL STATE
# =============================================================================

class SQLState(TypedDict):
    # INPUT
    user_query: str
    query_type: str
    active_context: Optional[ActiveQueryContext]
    conversation_history: List[Dict[str, Any]]
    reference_context: Optional[Dict[str, Any]]
    # INTERNAL — generic_text2sql pipeline fields
    parsed_intent: Optional[Dict]
    enriched_metadata: Optional[Dict]
    resolved_steps: Optional[List[Dict]]
    sql_queries: Optional[List[str]]
    schema_metadata: Optional[Dict]
    business_rules: Optional[Dict]
    business_rules_context: Optional[str]
    merged_sql_components: Optional[Dict]
    applied_business_rules: Optional[List[Dict]]
    detected_tables: Optional[List[str]]
    resolution_metadata: Optional[Dict]
    retry_count: Optional[int]
    sql_error_history: Optional[List[Dict]]
    no_records_message: Optional[str]
    error: Optional[str]              # sql_executor error output
    _execution_mode: Optional[str]    # "full" | "delta"
    _delta_fallback: Optional[bool]
    _delta_changes: Optional[Dict]
    _sql_context_hint: Optional[str]
    _conversation_entry: Optional[Dict[str, Any]]    # update_history_node writes this
    _last_query_results: Optional[Dict[str, Any]]    # update_history_node writes this
    # OUTPUT
    results: Optional[List[Dict]]
    sql_result: Optional[SQLResult]


# =============================================================================
# INPUT FACTORY
# =============================================================================

def create_sql_input(
    orch_state: OrchestratorState,
    classify_result: ClassifyResult
) -> SQLState:
    """
    Maps OrchestratorState + ClassifyResult → SQLState.

    Called by the orchestrator before invoking the SQL agent.
    """
    return SQLState(
        user_query=classify_result["user_query"],
        query_type=classify_result.get("query_type", "unknown"),
        active_context=orch_state.get("active_context"),
        conversation_history=orch_state.get("conversation_history", []),
        reference_context=classify_result.get("reference_context"),
        # INTERNAL — all None / zero at entry
        parsed_intent=None,
        enriched_metadata=None,
        resolved_steps=None,
        sql_queries=None,
        schema_metadata=None,
        business_rules=None,
        business_rules_context=None,
        merged_sql_components=None,
        applied_business_rules=None,
        detected_tables=None,
        resolution_metadata=None,
        retry_count=0,
        sql_error_history=None,
        no_records_message=None,
        error=None,
        _execution_mode=None,
        _delta_fallback=False,
        _delta_changes=None,
        _sql_context_hint=None,
        _conversation_entry=None,
        _last_query_results=None,
        # OUTPUT
        results=None,
        sql_result=None,
    )


# =============================================================================
# HELPERS — migrated private functions from nodes.py
# =============================================================================

def _enrich_query_with_context(
    user_query: str,
    active_context: Dict[str, Any]
) -> str:
    """
    Enrich user query with context filters (for contextual_full mode).

    Converts context filters to natural language and prepends to user query.
    Migrated from _enrich_query_with_context() in nodes.py.
    """
    filters = active_context.get("applied_filters", [])

    if not filters:
        return user_query

    filter_phrases = []
    for f in filters:
        column = f.get("column", "")
        value = f.get("value", "")
        operator = f.get("operator", "=")

        if not column or not value:
            continue

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

    filter_text = ", ".join(filter_phrases)
    enriched_query = f"{filter_text} için {user_query}"

    logger.info(f"[CONTEXT_ENRICH] Original: '{user_query}' → Enriched: '{enriched_query}'")
    return enriched_query


def _build_conversation_context(
    active_context: Optional[Dict[str, Any]],
    conversation_history: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Build conversation context dict for Text2SQL nodes.

    Migrated from _build_conversation_context() in nodes.py.
    Accepts conversation_history directly (no full ReportState needed).
    """
    if not active_context:
        return None

    context: Dict[str, Any] = {
        "has_previous_query": True,
        "previous_table": active_context.get("current_table", ""),
        "previous_sql": active_context.get("current_sql", ""),
        "previous_filters": active_context.get("applied_filters", []),
        "previous_grouping": active_context.get("grouping_columns", []),
        "previous_ordering": active_context.get("order_by_columns", []),
        "result_row_count": active_context.get("result_row_count", 0),
        "last_execution_time": active_context.get("last_execution_time", ""),
        "confidence_score": active_context.get("confidence_score", 0.0),
    }

    if conversation_history:
        context["query_count"] = len(conversation_history)
        context["last_version"] = len(conversation_history)

    return context


def _determine_execution_mode(
    intent_type: str,
    active_context: Optional[Dict[str, Any]],
    confidence: float
) -> str:
    """
    Determine execution mode based on intent and context.

    Modes:
    - "full":           Complete pipeline (new query or no context)
    - "contextual_full": Full rebuild preserving context filters
    - "delta":          Incremental SQL modification
    - "reuse":          Reuse existing data (viz change only)

    Migrated from _determine_execution_mode() in nodes.py.
    Simplified: last_intent parameter removed (not needed in V2 architecture).
    """
    if not active_context:
        logger.debug("[EXECUTION_MODE] No active context → full")
        return "full"

    if confidence < 0.7:
        logger.debug(f"[EXECUTION_MODE] Low confidence ({confidence:.2f}) → full")
        return "full"

    contextual_full_intents = {"modify_filter", "add_filter", "remove_filter"}
    delta_only_intents = {"modify_aggregation", "modify_columns", "modify_order"}

    if intent_type in contextual_full_intents:
        logger.debug(f"[EXECUTION_MODE] Filter modification '{intent_type}' → contextual_full")
        return "contextual_full"

    if intent_type in delta_only_intents:
        logger.debug(f"[EXECUTION_MODE] Delta intent '{intent_type}' → delta")
        return "delta"

    logger.debug(f"[EXECUTION_MODE] Intent '{intent_type}' → full")
    return "full"


# =============================================================================
# NODE 1: extract_and_prepare_node
# =============================================================================

async def extract_and_prepare_node(state: SQLState) -> Dict[str, Any]:
    """
    Extract and prepare query for the Text2SQL pipeline.

    Migrated from extract_query_node() in nodes.py.
    - Injects reference context (follow-up queries) into user_query
    - Handles comparison follow-up grouping preservation
    - Sets _sql_context_hint for downstream Text2SQL nodes
    """
    user_query = state.get("user_query", "")

    if not user_query:
        logger.error("[SQL_AGENT] [EXTRACT] No user_query found")
        return {"sql_result": SQLResult(
            results=[], sql_query="", no_records_message=None,
            updated_active_context=None, conversation_entry=None,
            error="No user query found"
        )}

    logger.info(f"[SQL_AGENT] [EXTRACT] Processing query: {user_query[:100]}...")

    # =========================================================================
    # PHASE 4: CONTEXT INJECTION FOR FOLLOW-UP QUERIES
    # =========================================================================
    reference_context = state.get("reference_context") or {}
    conversation_history = state.get("conversation_history") or []
    is_followup = reference_context.get("is_followup", False)

    # Derive last_query_results from conversation_history
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

    logger.info(f"[SQL_AGENT] [EXTRACT] Context injection check: is_followup={is_followup}, "
                f"has_last_results={last_query_results is not None}")

    sql_context_hint = ""

    if is_followup and last_query_results:
        prev_entities = last_query_results.get("entities", [])
        entity_type = last_query_results.get("entity_type", "entity")

        if prev_entities:
            # SQL injection prevention: escape single quotes
            entities_escaped = [str(e).replace("'", "''") for e in prev_entities[:20]]
            entities_str = "', '".join(entities_escaped)

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
            enriched_query = f"{user_query}\n\n{sql_context_hint}"
            logger.info(f"[SQL_AGENT] [EXTRACT] Context injection: {len(prev_entities)} {entity_type} entities")
            user_query = enriched_query

    # =========================================================================
    # COMPARISON FOLLOW-UP: preserve grouping from previous query
    # =========================================================================
    active_context = state.get("active_context")

    if is_followup and conversation_history and active_context:
        last_conv = conversation_history[-1]
        prev_grouping = last_conv.get("grouping", [])
        prev_filters = last_conv.get("filters", [])

        user_lower = user_query.lower()
        comparison_keywords = ["karşılaştır", "kıyasla", " vs ", "ile karşılaştır", "ile kıyasla"]
        is_comparison_followup = any(kw in user_lower for kw in comparison_keywords)

        if is_comparison_followup and (prev_grouping or prev_filters):
            logger.info(f"[SQL_AGENT] [EXTRACT] Comparison follow-up detected, preserving grouping")

            grouping_hint = ""
            if prev_grouping:
                grouping_cols = ", ".join(prev_grouping)
                grouping_hint = (
                    f"\n\n⚠️ KRİTİK: Önceki sorgu '{grouping_cols}' ile gruplanmıştı. "
                    f"YENİ sorgu da AYNI GRUPLAMA ile yapılmalı (GROUP BY {grouping_cols})!"
                )

            filter_hint = ""
            if prev_filters:
                time_filters = [f for f in prev_filters if "DocumentDate" in f.get("column", "")]
                if time_filters:
                    filter_hint = f"\n\n⚠️ Önceki zaman filtresi korunmalı: {time_filters}"

            if grouping_hint or filter_hint:
                user_query = f"{user_query}{grouping_hint}{filter_hint}"
                logger.info(f"[SQL_AGENT] [EXTRACT] Enhanced query with preservation hints")

    # =========================================================================
    # BUILD CONVERSATION CONTEXT for Text2SQL nodes
    # =========================================================================
    conversation_context = _build_conversation_context(active_context, conversation_history)
    if conversation_context:
        logger.info(f"[SQL_AGENT] [EXTRACT] Built conversation context: {list(conversation_context.keys())}")

    # =========================================================================
    # CONTEXTUAL FULL: Enrich query if mode requires it
    # =========================================================================
    # We perform a preliminary mode check here to decide whether to enrich
    # the query. The _execution_mode is set definitively in detect_execution_mode_node.
    query_type = state.get("query_type", "")
    # Treat any modify_filter type as potentially contextual_full
    # (final mode confirmed in detect_execution_mode_node)
    if query_type in {"modify_filter", "add_filter", "remove_filter"} and active_context:
        enriched_query = _enrich_query_with_context(user_query, active_context)
        if enriched_query != user_query:
            logger.info(f"[SQL_AGENT] [EXTRACT] [CONTEXTUAL_FULL] Query enriched with context filters")
            user_query = enriched_query

    result: Dict[str, Any] = {
        "user_query": user_query,
        "_sql_context_hint": sql_context_hint if sql_context_hint else None,
    }

    return result


# =============================================================================
# NODE 2: build_query_type_context_node
# =============================================================================

async def build_query_type_context_node(state: SQLState) -> Dict[str, Any]:
    """
    Build SQL context hints based on query_type.

    Migrated from build_query_type_context_node() in query_type_actions.py.
    Operates without LLM (rule-based fallback only) to keep the node
    dependency-free at construction time.
    LLM-enhanced extraction can be wired in via the factory if needed.
    """
    from src.graphs.report.query_type_actions import build_query_type_context_node as _upstream_node
    from src.graphs.report.state import ReportState

    query_type = state.get("query_type")
    user_query = state.get("user_query")

    if not query_type or not user_query:
        logger.info("[SQL_AGENT] [QT_CONTEXT] No query_type or user_query, skipping")
        return {}

    logger.info(f"[SQL_AGENT] [QT_CONTEXT] Building context for query_type='{query_type}'")

    # Build a minimal state-like dict compatible with the upstream function
    minimal_state: Dict[str, Any] = {
        "query_type": query_type,
        "user_query": user_query,
    }

    try:
        # Call upstream function — no LLM (rule-based entity extraction)
        result = await _upstream_node(minimal_state, llm=None)
        logger.info(f"[SQL_AGENT] [QT_CONTEXT] Context built: {list(result.keys())}")
        return result
    except Exception as e:
        logger.error(f"[SQL_AGENT] [QT_CONTEXT] Error building context: {e}", exc_info=True)
        return {}


# =============================================================================
# NODE 3: detect_execution_mode_node
# =============================================================================

async def detect_execution_mode_node(state: SQLState) -> Dict[str, Any]:
    """
    Determine execution mode (full / contextual_full / delta / reuse).

    Sets _execution_mode. Normalises contextual_full → full since the V2
    pipeline does not have a separate "contextual_full" branch (query
    enrichment already happened in extract_and_prepare_node).

    Migrated from _determine_execution_mode() in nodes.py.
    """
    query_type = state.get("query_type", "")
    active_context = state.get("active_context")
    reference_context = state.get("reference_context") or {}

    # Use confidence from reference_context if available
    confidence = reference_context.get("query_type_confidence", 1.0)

    execution_mode = _determine_execution_mode(
        intent_type=query_type,
        active_context=active_context,
        confidence=confidence,
    )

    # Normalise contextual_full → full (enrichment already applied)
    if execution_mode == "contextual_full":
        execution_mode = "full"

    logger.info(f"[SQL_AGENT] [EXEC_MODE] Execution mode: {execution_mode}")

    return {"_execution_mode": execution_mode}


# =============================================================================
# NODE 4: delta_sql_modifier_node
# =============================================================================

async def delta_sql_modifier_node(state: SQLState) -> Dict[str, Any]:
    """
    Delta SQL modifier — modify existing SQL without full rebuild.

    Migrated from delta_sql_modifier_node() in nodes.py.
    State field names adapted: active_query_context → active_context.

    On success: sets sql_queries, _delta_changes, _delta_fallback=False.
    On failure: sets _delta_fallback=True (triggers full pipeline routing).
    """
    from src.graphs.report.delta_parser import AdvancedDeltaParser, SQLModifier

    logger.info("=" * 80)
    logger.info("[SQL_AGENT] [DELTA_SQL] Starting delta SQL modification")

    try:
        active_context = state.get("active_context")
        user_query = state.get("user_query", "")
        query_type = state.get("query_type", "")

        if not active_context:
            logger.error("[SQL_AGENT] [DELTA_SQL] No active context — cannot perform delta update")
            return {"_delta_fallback": True}

        base_sql = active_context.get("current_sql", "")
        if not base_sql:
            logger.error("[SQL_AGENT] [DELTA_SQL] No base SQL in active context")
            return {"_delta_fallback": True}

        logger.info(f"[SQL_AGENT] [DELTA_SQL] Base SQL: {base_sql[:200]}...")
        logger.info(f"[SQL_AGENT] [DELTA_SQL] Intent: {query_type}")
        logger.info(f"[SQL_AGENT] [DELTA_SQL] User query: {user_query[:100]}...")

        # Attempt to initialise ValueResolver for column name resolution
        value_resolver = None
        try:
            from src.graphs.generic_text2sql.value_resolver_service import ValueResolverService
            import os

            db_connection_string = os.getenv("DATABASE_URL")
            table_name = active_context.get("current_table", "MasterReportDocumentTable")

            if db_connection_string:
                value_resolver = ValueResolverService(
                    db_connection_string=db_connection_string,
                    table_name=table_name
                )
                value_resolver._init_column_semantic_mapping()
                logger.info(f"[SQL_AGENT] [DELTA_SQL] ValueResolver initialised for: {table_name}")
        except Exception as e:
            logger.warning(f"[SQL_AGENT] [DELTA_SQL] ValueResolver init failed (non-fatal): {e}")
            value_resolver = None

        # Get column metadata for column name resolution
        column_metadata = state.get("schema_metadata")

        # Parse delta changes using LLM-based AdvancedDeltaParser
        try:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            parser = AdvancedDeltaParser(llm)

            delta_changes = await parser.parse_advanced_delta(
                user_query=user_query,
                active_context=active_context,
                intent_type=query_type,
                schema_metadata=column_metadata,
            )
        except Exception as e:
            logger.warning(f"[SQL_AGENT] [DELTA_SQL] LLM delta parsing failed: {e}")
            delta_changes = None

        if not delta_changes or delta_changes.get("modification_type") == "unknown":
            logger.warning("[SQL_AGENT] [DELTA_SQL] Cannot parse delta changes → full fallback")
            return {"_delta_fallback": True}

        confidence = delta_changes.get("confidence", 0.0)
        if confidence < 0.6:
            logger.warning(f"[SQL_AGENT] [DELTA_SQL] Low confidence ({confidence:.2f}) → full fallback")
            return {"_delta_fallback": True}

        # Resolve semantic column names if ValueResolver available
        if value_resolver:
            delta_changes = _resolve_delta_column_names(delta_changes, value_resolver)

        # Apply delta modifications
        modified_sql = _apply_sql_delta(base_sql, delta_changes, active_context, value_resolver)

        logger.info(f"[SQL_AGENT] [DELTA_SQL] Modified SQL: {modified_sql[:200]}...")
        logger.info("[SQL_AGENT] [DELTA_SQL] Delta modification completed")
        logger.info("=" * 80)

        return {
            "sql_queries": [modified_sql],
            "_delta_fallback": False,
            "_delta_changes": delta_changes,
        }

    except Exception as e:
        logger.error(f"[SQL_AGENT] [DELTA_SQL] Error: {e}", exc_info=True)
        logger.warning("[SQL_AGENT] [DELTA_SQL] Falling back to full execution")
        return {"_delta_fallback": True}


def _resolve_delta_column_names(
    delta_changes: Dict[str, Any],
    value_resolver
) -> Dict[str, Any]:
    """
    Resolve semantic column names in delta_changes to actual DB column names.
    Migrated from _resolve_delta_column_names() in nodes.py.
    """
    try:
        # Resolve filters_to_add
        for f in delta_changes.get("filters_to_add", []):
            if isinstance(f, dict) and f.get("column"):
                original = f["column"]
                try:
                    resolved = value_resolver.resolve_column_name(original)
                    if resolved and resolved != original:
                        f["column"] = resolved
                        logger.debug(f"[DELTA_RESOLVE] Filter column: {original} → {resolved}")
                except Exception:
                    pass

        # Resolve filters_to_remove
        for f in delta_changes.get("filters_to_remove", []):
            if isinstance(f, dict) and f.get("column"):
                original = f["column"]
                try:
                    resolved = value_resolver.resolve_column_name(original)
                    if resolved and resolved != original:
                        f["column"] = resolved
                except Exception:
                    pass

        # Resolve columns_to_add
        resolved_add = []
        for col in delta_changes.get("columns_to_add", []):
            try:
                resolved = value_resolver.resolve_column_name(col)
                resolved_add.append(resolved if resolved else col)
            except Exception:
                resolved_add.append(col)
        delta_changes["columns_to_add"] = resolved_add

        # Resolve columns_to_remove
        resolved_remove = []
        for col in delta_changes.get("columns_to_remove", []):
            try:
                resolved = value_resolver.resolve_column_name(col)
                resolved_remove.append(resolved if resolved else col)
            except Exception:
                resolved_remove.append(col)
        delta_changes["columns_to_remove"] = resolved_remove

        # Resolve ordering_change column
        ordering = delta_changes.get("ordering_change")
        if ordering and isinstance(ordering, dict) and ordering.get("column"):
            original = ordering["column"]
            try:
                resolved = value_resolver.resolve_column_name(original)
                if resolved:
                    ordering["column"] = resolved
            except Exception:
                pass

    except Exception as e:
        logger.warning(f"[DELTA_RESOLVE] Error during resolution (non-fatal): {e}")

    return delta_changes


def _apply_sql_delta(
    base_sql: str,
    delta_changes: Dict[str, Any],
    active_context: Dict[str, Any],
    value_resolver=None
) -> str:
    """
    Apply delta changes to base SQL.

    Migrated from _apply_sql_delta() in nodes.py.
    Uses SQLModifier for column/aggregation operations.
    """
    import re
    from src.graphs.report.delta_parser import SQLModifier

    modified_sql = base_sql
    parsing_method = delta_changes.get("parsing_method", "unknown")

    logger.info(f"[SQL_AGENT] [DELTA_APPLY] Applying delta changes (method: {parsing_method})")

    sql_modifier = SQLModifier(value_resolver)

    # Column additions
    columns_to_add = delta_changes.get("columns_to_add", [])
    if columns_to_add:
        logger.info(f"[SQL_AGENT] [DELTA_APPLY] Adding {len(columns_to_add)} columns")
        modified_sql = sql_modifier.add_columns(modified_sql, columns_to_add)

    # Column removals
    columns_to_remove = delta_changes.get("columns_to_remove", [])
    if columns_to_remove:
        logger.info(f"[SQL_AGENT] [DELTA_APPLY] Removing {len(columns_to_remove)} columns")
        modified_sql = sql_modifier.remove_columns(modified_sql, columns_to_remove)

    # Aggregation changes
    aggregation_changes = delta_changes.get("aggregation_changes", {})
    if aggregation_changes:
        logger.info("[SQL_AGENT] [DELTA_APPLY] Applying aggregation changes")
        modified_sql = sql_modifier.modify_aggregations(modified_sql, aggregation_changes)

    # Structured filter additions (from LLM)
    filters_to_add = delta_changes.get("filters_to_add", [])
    if filters_to_add and isinstance(filters_to_add[0], dict) and "column" in filters_to_add[0]:
        for filter_def in filters_to_add:
            column = filter_def.get("column")
            operator = filter_def.get("operator", "=")
            value = filter_def.get("value")

            if not column or not value:
                continue

            filter_clause = f"{column} {operator} '{value}'"

            if "WHERE" in modified_sql.upper():
                where_match = re.search(r'\bWHERE\b', modified_sql, re.IGNORECASE)
                if where_match:
                    pos = where_match.end()
                    modified_sql = modified_sql[:pos] + f" {filter_clause} AND " + modified_sql[pos:]
            else:
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

            logger.info(f"[SQL_AGENT] [DELTA_APPLY] Added filter: {filter_clause}")

    # Limit changes
    limit_change = delta_changes.get("limit_change")
    if limit_change and isinstance(limit_change, int):
        if "TOP" in modified_sql.upper():
            modified_sql = re.sub(
                r'\bTOP\s+\d+\b',
                f"TOP {limit_change}",
                modified_sql,
                count=1,
                flags=re.IGNORECASE
            )
        elif "LIMIT" in modified_sql.upper():
            modified_sql = re.sub(
                r'\bLIMIT\s+\d+\b',
                f"LIMIT {limit_change}",
                modified_sql,
                count=1,
                flags=re.IGNORECASE
            )
        else:
            modified_sql = f"SELECT TOP {limit_change} * FROM ({modified_sql}) AS delta_subquery"
        logger.info(f"[SQL_AGENT] [DELTA_APPLY] Applied limit change: {limit_change}")

    # Ordering changes
    ordering_change = delta_changes.get("ordering_change")
    if ordering_change and isinstance(ordering_change, dict):
        col = ordering_change.get("column")
        direction = ordering_change.get("direction", "DESC")
        if col and not ordering_change.get("_needs_parsing"):
            if "ORDER BY" in modified_sql.upper():
                modified_sql = re.sub(
                    r'\bORDER BY\s+\S+\s*(ASC|DESC)?',
                    f"ORDER BY {col} {direction}",
                    modified_sql,
                    count=1,
                    flags=re.IGNORECASE
                )
            else:
                modified_sql = f"{modified_sql} ORDER BY {col} {direction}"
            logger.info(f"[SQL_AGENT] [DELTA_APPLY] Applied ordering: {col} {direction}")

    return modified_sql


# =============================================================================
# NODE 5: update_history_node
# =============================================================================

async def update_history_node(state: SQLState) -> Dict[str, Any]:
    """
    Update conversation history after SQL execution.

    Migrated from update_conversation_history_node() in nodes.py.
    State field names adapted for SQLState:
    - text2sql_output → results (direct results field)
    - active_query_context → active_context
    - query_type → query_type (already present in SQLState)

    Note: Returns a conversation_entry dict for the orchestrator to store.
    """
    results = state.get("results") or []
    user_query = state.get("user_query", "")
    query_type = state.get("query_type")
    active_context = state.get("active_context")
    conversation_history = list(state.get("conversation_history") or [])

    if not results:
        logger.info("[SQL_AGENT] [HISTORY] No results, skipping history update")
        return {}

    # Extract entities from results for follow-up support
    extracted_entities_dict: Dict[str, Any] = {}
    if results and len(results) > 0:
        first_key = list(results[0].keys())[0]
        entities_from_results = [r.get(first_key) for r in results[:10] if r.get(first_key)]
        extracted_entities_dict = {
            "entities": entities_from_results,
            "entity_column": first_key,
            "entity_type": first_key,
            "source": "results",
        }

    new_entry = {
        "query": user_query,
        "query_type": query_type,
        "results": results[:10],
        "timestamp": datetime.now().isoformat(),
        "extracted_entities": extracted_entities_dict,
        "filters": (active_context or {}).get("applied_filters", []),
        "grouping": (active_context or {}).get("grouping_columns", []),
    }
    conversation_history.append(new_entry)

    # Keep only last 5 queries
    if len(conversation_history) > 5:
        conversation_history = conversation_history[-5:]

    # Build last_query_results for next follow-up
    last_query_results = None
    if results and len(results) > 0:
        first_key = list(results[0].keys())[0]
        entities = [r.get(first_key) for r in results]

        entity_type = "unknown"
        fk_lower = first_key.lower()
        if "branch" in fk_lower or "sube" in fk_lower:
            entity_type = "branch"
        elif "product" in fk_lower or "urun" in fk_lower:
            entity_type = "product"
        elif "category" in fk_lower or "kategori" in fk_lower:
            entity_type = "category"
        elif "city" in fk_lower or "sehir" in fk_lower:
            entity_type = "city"
        elif "customer" in fk_lower or "musteri" in fk_lower:
            entity_type = "customer"

        last_query_results = {
            "entities": entities,
            "entity_type": entity_type,
            "filters": {f"{first_key}__in": entities},
        }

    logger.info(f"[SQL_AGENT] [HISTORY] Updated: {len(conversation_history)} entries")

    return {
        "conversation_history": conversation_history,
        # Store as conversation_entry for orchestrator to pick up
        "_conversation_entry": new_entry,
        "_last_query_results": last_query_results,
    }


# =============================================================================
# NODE 6: build_sql_result_node
# =============================================================================

async def build_sql_result_node(state: SQLState) -> Dict[str, Any]:
    """
    Assemble the SQLResult TypedDict from state fields.

    This is the terminal node of the SQL agent.
    It packages all outputs into a typed contract for the orchestrator.
    """
    results = state.get("results") or []
    sql_queries = state.get("sql_queries") or []
    sql_query = sql_queries[-1] if sql_queries else ""
    no_records_message = state.get("no_records_message")
    active_context = state.get("active_context")
    error = state.get("error")  # Error key used by text2sql pipeline nodes
    conversation_entry = state.get("_conversation_entry")

    # Build updated active context from execution results
    updated_active_context: Optional[ActiveQueryContext] = None
    if results and sql_query and active_context is not None:
        current_table = (active_context or {}).get("current_table", "")
        updated_active_context = ActiveQueryContext(
            current_table=current_table,
            current_sql=sql_query,
            applied_filters=[],     # Would need to extract from SQL — left to orchestrator
            grouping_columns=[],
            order_by_columns=[],
            result_sample=results[:5] if results else None,
            result_row_count=len(results),
            last_execution_time=datetime.now().isoformat(),
            confidence_score=1.0,
        )
    elif results and sql_query and active_context is None:
        # First query — create fresh context
        updated_active_context = ActiveQueryContext(
            current_table="",
            current_sql=sql_query,
            applied_filters=[],
            grouping_columns=[],
            order_by_columns=[],
            result_sample=results[:5] if results else None,
            result_row_count=len(results),
            last_execution_time=datetime.now().isoformat(),
            confidence_score=1.0,
        )

    sql_result: SQLResult = {
        "results": results,
        "sql_query": sql_query,
        "no_records_message": no_records_message,
        "updated_active_context": updated_active_context,
        "conversation_entry": conversation_entry,
        "error": error,
    }

    logger.info(f"[SQL_AGENT] [BUILD_RESULT] SQLResult assembled: "
                f"{len(results)} rows, sql_query={bool(sql_query)}, error={bool(error)}")

    return {"sql_result": sql_result}


# =============================================================================
# ROUTING
# =============================================================================

def route_after_execution_mode(state: SQLState) -> str:
    """
    Route after detect_execution_mode.

    - "delta" mode → delta_sql_modifier
    - everything else → create_table (full pipeline)
    """
    execution_mode = state.get("_execution_mode", "full")

    if execution_mode == "delta":
        logger.info("[SQL_AGENT] [ROUTE] Delta mode → delta_sql_modifier")
        return "delta_sql_modifier"

    logger.info(f"[SQL_AGENT] [ROUTE] {execution_mode} mode → create_table")
    return "create_table"


def route_after_delta(state: SQLState) -> str:
    """
    Route after delta_sql_modifier.

    - _delta_fallback=True  → create_table (full pipeline fallback)
    - _delta_fallback=False → sql_executor (skip heavy nodes)
    """
    if state.get("_delta_fallback"):
        logger.info("[SQL_AGENT] [ROUTE] Delta fallback → create_table (full pipeline)")
        return "create_table"

    logger.info("[SQL_AGENT] [ROUTE] Delta success → sql_executor")
    return "sql_executor"


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_sql_agent(node_kit=None, llm=None):
    """
    Build and compile the SQL agent LangGraph.

    Args:
        node_kit: GenericText2SQLNodeKit instance. If None, a MagicMock-friendly
                  stub is used (for testing/compilation verification).
        llm: Optional LLM (reserved for future use — currently unused by this agent).

    Returns:
        Compiled LangGraph StateGraph (CompiledStateGraph).

    Node order (full pipeline):
        extract_and_prepare
        build_query_type_context
        detect_execution_mode
        [delta path] delta_sql_modifier → sql_executor
        [full path]  create_table → sql_architect → retrieve_business_rules
                     → metadata_enrichment → value_resolver
                     → sql_query_builder → sql_executor
        update_history
        build_sql_result
    """
    from src.graphs.generic_text2sql.node_factories import create_all_text2sql_nodes

    text2sql_nodes = create_all_text2sql_nodes(node_kit)

    # Expected node names from create_all_text2sql_nodes:
    #   sql_architect, value_resolver, metadata_enrichment,
    #   retrieve_business_rules, sql_query_builder,
    #   create_table, sql_executor, cleanup_table

    graph = StateGraph(SQLState)

    # -------------------------------------------------------------------------
    # Pre-pipeline nodes
    # -------------------------------------------------------------------------
    graph.add_node("extract_and_prepare", extract_and_prepare_node)
    graph.add_node("build_query_type_context", build_query_type_context_node)
    graph.add_node("detect_execution_mode", detect_execution_mode_node)
    graph.add_node("delta_sql_modifier", delta_sql_modifier_node)

    # -------------------------------------------------------------------------
    # Text2SQL pipeline nodes (from generic_text2sql node_factories)
    # -------------------------------------------------------------------------
    for name, node_fn in text2sql_nodes.items():
        graph.add_node(name, node_fn)

    # -------------------------------------------------------------------------
    # Post-pipeline nodes
    # -------------------------------------------------------------------------
    graph.add_node("update_history", update_history_node)
    graph.add_node("build_sql_result", build_sql_result_node)

    # -------------------------------------------------------------------------
    # Edges — sequential pre-pipeline
    # -------------------------------------------------------------------------
    graph.add_edge(START, "extract_and_prepare")
    graph.add_edge("extract_and_prepare", "build_query_type_context")
    graph.add_edge("build_query_type_context", "detect_execution_mode")

    # -------------------------------------------------------------------------
    # Conditional: delta vs full pipeline
    # -------------------------------------------------------------------------
    graph.add_conditional_edges(
        "detect_execution_mode",
        route_after_execution_mode,
        {
            "delta_sql_modifier": "delta_sql_modifier",
            "create_table": "create_table",
        }
    )

    # Delta node: on failure falls back to full pipeline
    graph.add_conditional_edges(
        "delta_sql_modifier",
        route_after_delta,
        {
            "sql_executor": "sql_executor",
            "create_table": "create_table",
        }
    )

    # -------------------------------------------------------------------------
    # Edges — full Text2SQL pipeline (unchanged pipeline order from graph.py)
    # create_table → sql_architect → retrieve_business_rules
    # → metadata_enrichment → value_resolver → sql_query_builder
    # → sql_executor
    # -------------------------------------------------------------------------
    graph.add_edge("create_table", "sql_architect")
    graph.add_edge("sql_architect", "retrieve_business_rules")
    graph.add_edge("retrieve_business_rules", "metadata_enrichment")
    graph.add_edge("metadata_enrichment", "value_resolver")
    graph.add_edge("value_resolver", "sql_query_builder")
    graph.add_edge("sql_query_builder", "sql_executor")

    # -------------------------------------------------------------------------
    # Post-execution
    # -------------------------------------------------------------------------
    graph.add_edge("sql_executor", "cleanup_table")
    graph.add_edge("cleanup_table", "update_history")
    graph.add_edge("update_history", "build_sql_result")
    graph.add_edge("build_sql_result", END)

    return graph.compile()
