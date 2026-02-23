"""
Text2SQL Subagent Nodes

5 node:
    sql_planner          - LLM: user_query → QueryPlan
    value_resolver       - Pure Python: value_hints → resolved DB değerleri
    business_rules       - Pure Python: user_query → SQL components (ChromaDB)
    sql_builder          - LLM: QueryPlan (resolved) + rules → T-SQL
    sql_executor         - Pure Python: SQL çalıştır, hata → retry
"""
import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pyodbc

from src.graphs.report_agent.subagents.text2sql.prompts import (
    FixedSQL,
    GeneratedSQL,
    QueryPlan,
    SQL_BUILDER_PROMPT,
    QUERY_PLANNER_PROMPT,
)
from src.graphs.report_agent.subagents.text2sql.value_resolver_service import ValueResolverService
from src.graphs.report_agent.subagents.text2sql.business_rules_vector_store import BusinessRulesVectorStore

logger = logging.getLogger(__name__)

_db_executor = ThreadPoolExecutor(max_workers=3)
MAX_RETRY = 2


# =============================================================================
# DB UTILITY
# =============================================================================

def _serialize_row(columns: List[str], row: Any) -> Dict[str, Any]:
    """pyodbc Row → dict, Decimal güvenli."""
    record = {}
    for col, val in zip(columns, row):
        record[col] = float(val) if isinstance(val, Decimal) else val
    return record


async def _execute_sql_async(connection_string: str, sql: str) -> List[Dict[str, Any]]:
    """SQL'i thread pool'da async çalıştır."""
    loop = asyncio.get_event_loop()

    def _run():
        conn = pyodbc.connect(connection_string, timeout=30)
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        return [_serialize_row(columns, row) for row in rows]

    return await loop.run_in_executor(_db_executor, _run)


# =============================================================================
# NODE 1: SQL PLANNER
# =============================================================================

def create_sql_planner_node(llm, column_metadata: Dict[str, Any]) -> Callable:
    """
    LLM: user_query + query_type → QueryPlan.

    Single Responsibility: Kullanıcı niyetini yapısal sorgu planına çevirmek.
    """
    structured_llm = llm.with_structured_output(QueryPlan)

    async def sql_planner_node(state: dict) -> dict:
        user_query = state.get("user_query", "")
        query_type = state.get("query_type", "SINGLE")
        active_sql = state.get("active_sql")
        active_filters = state.get("active_filters") or []

        conversation_context = "Yeni sorgu, önceki bağlam yok."
        if active_sql:
            conversation_context = f"Önceki SQL: {active_sql[:300]}"
            if active_filters:
                filters_str = json.dumps(active_filters[:3], ensure_ascii=False)
                conversation_context += f"\nAktif filtreler: {filters_str}"

        prompt = QUERY_PLANNER_PROMPT.format(
            user_query=user_query,
            query_type=query_type,
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
            conversation_context=conversation_context,
        )

        logger.info(f"[SQL_PLANNER] Planning: {user_query[:80]} (type={query_type})")
        plan: QueryPlan = await structured_llm.ainvoke(prompt)
        logger.info(
            f"[SQL_PLANNER] Plan: filters={len(plan.filters)}, "
            f"aggs={len(plan.aggregations)}, limit={plan.limit}"
        )
        return {"query_plan": plan.model_dump()}

    return sql_planner_node


# =============================================================================
# NODE 2: VALUE RESOLVER
# =============================================================================

def create_value_resolver_node(value_resolver: ValueResolverService) -> Callable:
    """
    Pure Python: QueryPlan.filters[].value_hint → resolved_value.

    Single Responsibility: Fuzzy matching ile DB değerlerini bulmak.
    """

    async def value_resolver_node(state: dict) -> dict:
        query_plan = state.get("query_plan")
        if not query_plan or not query_plan.get("filters"):
            return {}

        filters = query_plan["filters"]
        resolved_any = False

        for f in filters:
            field_hint = f.get("field_hint", "")
            value_hint = f.get("value_hint", "")

            if not value_hint or f.get("resolved_value"):
                continue

            # field_hint → DB kolon adı (semantic map kullan)
            db_column = value_resolver.resolve_column_name(field_hint)
            if not db_column:
                logger.debug(f"[VALUE_RESOLVER] No column for field_hint='{field_hint}'")
                continue

            result = await value_resolver.resolve(value_hint, db_column)
            if result and result.get("confidence", 0) >= 75:
                f["resolved_value"] = result["resolved"]
                resolved_any = True
                logger.info(
                    f"[VALUE_RESOLVER] '{value_hint}' → '{result['resolved']}' "
                    f"(conf={result['confidence']})"
                )
            else:
                logger.debug(
                    f"[VALUE_RESOLVER] Low confidence for '{value_hint}' in '{db_column}'"
                )

        if resolved_any:
            return {"query_plan": query_plan}
        return {}

    return value_resolver_node


# =============================================================================
# NODE 3: BUSINESS RULES
# =============================================================================

def create_business_rules_node(vector_store: BusinessRulesVectorStore) -> Callable:
    """
    Pure Python: user_query → merged SQL components (ChromaDB semantic search).

    Single Responsibility: Alakalı business rule SQL bileşenlerini bulmak.
    """

    async def business_rules_node(state: dict) -> dict:
        user_query = state.get("user_query", "")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _db_executor,
            lambda: vector_store.get_relevant_rules_for_query(
                user_query=user_query,
                n_results=5,
                use_hybrid=True,
            ),
        )

        merged = result.get("merged_sql", {})
        if not merged:
            logger.info("[BUSINESS_RULES] No relevant rules found")
            return {"business_rules_context": ""}

        # Merged SQL components'i prompt-friendly string'e çevir
        parts = []
        for component, value in merged.items():
            if value:
                parts.append(f"{component.upper()}: {value}")

        context = "\n".join(parts)
        logger.info(
            f"[BUSINESS_RULES] Found {result['total_count']} rules "
            f"({result['default_count']} default, {result['semantic_count']} semantic)"
        )
        return {"business_rules_context": context}

    return business_rules_node


# =============================================================================
# NODE 4: SQL BUILDER
# =============================================================================

def create_sql_builder_node(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
) -> Callable:
    """
    LLM: QueryPlan (resolved) + business_rules + column_metadata → T-SQL.

    Single Responsibility: Geçerli T-SQL üretmek.
    Retry durumunda sql_error'ı alarak hatayı düzeltir.
    """
    structured_llm = llm.with_structured_output(GeneratedSQL)

    async def sql_builder_node(state: dict) -> dict:
        query_plan = state.get("query_plan", {})
        business_rules_context = state.get("business_rules_context") or "Uygulanacak rule yok."
        sql_error = state.get("sql_error") or ""

        prompt = SQL_BUILDER_PROMPT.format(
            table_name=table_name,
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
            query_plan=json.dumps(query_plan, ensure_ascii=False, indent=2),
            business_rules_context=business_rules_context,
            sql_error=sql_error if sql_error else "Yok",
        )

        logger.info(f"[SQL_BUILDER] Building SQL for table={table_name}"
                    + (f" (retry, error={sql_error[:80]})" if sql_error else ""))
        generated: GeneratedSQL = await structured_llm.ainvoke(prompt)
        logger.info(f"[SQL_BUILDER] SQL: {generated.sql[:150]}")

        return {
            "sql_queries": [generated.sql],
            "sql_error": None,   # Temizle — yeni SQL üretildi
        }

    return sql_builder_node


# =============================================================================
# NODE 5: SQL EXECUTOR
# =============================================================================

def create_sql_executor_node(connection_string: str) -> Callable:
    """
    Pure Python: SQL çalıştır, hata → retry mekanizması.

    Single Responsibility: SQL execution ve conversation context güncelleme.
    Retry kararı graph routing'de verilir (conditional edge).
    """

    async def sql_executor_node(state: dict) -> dict:
        sql_queries = state.get("sql_queries") or []
        if not sql_queries:
            return {"error": "Çalıştırılacak SQL bulunamadı.", "results": []}

        sql = sql_queries[0]
        retry_count = state.get("retry_count", 0)

        try:
            results = await _execute_sql_async(connection_string, sql)
            logger.info(f"[SQL_EXECUTOR] Success: {len(results)} rows")

            # Aktif filtreleri query_plan'dan çıkar (conversation context için)
            query_plan = state.get("query_plan") or {}
            active_filters = [
                {"field": f.get("field_hint"), "value": f.get("resolved_value") or f.get("value_hint")}
                for f in query_plan.get("filters", [])
            ]

            return {
                "results": results,
                "error": None,
                "sql_error": None,
                "retry_count": 0,
                "active_sql": sql,
                "active_results": results[:10],
                "active_filters": active_filters,
            }

        except Exception as e:
            error_msg = str(e)
            new_retry = retry_count + 1
            logger.warning(f"[SQL_EXECUTOR] Error (attempt {new_retry}/{MAX_RETRY}): {error_msg[:200]}")

            if new_retry <= MAX_RETRY:
                # Retry: sql_error set → graph sql_builder'a yönlendirir
                return {
                    "sql_error": error_msg,
                    "retry_count": new_retry,
                }
            else:
                # Max retry doldu
                logger.error(f"[SQL_EXECUTOR] Max retry reached, giving up.")
                return {
                    "error": f"SQL {MAX_RETRY} denemeden sonra başarısız oldu: {error_msg}",
                    "results": [],
                    "sql_error": None,
                }

    return sql_executor_node
