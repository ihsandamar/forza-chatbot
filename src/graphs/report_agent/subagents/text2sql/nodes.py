"""
Text2SQL Subagent Nodes (v2)

7 node:
    create_table         - Pure Python: tablo oluştur (no-op if no query config)
    business_rules       - Pure Python: ChromaDB semantic search → context + IDs
    sql_architect        - LLM (TEK ÇAĞRI): user_query → QuerySchema
    value_resolver       - Pure Python: fuzzy match + interrupt() if low confidence
    sql_generator        - Pure Python: QuerySchema → T-SQL (NO LLM)
    sql_executor         - Pure Python: SQL çalıştır, hata → retry
    cleanup_table        - Pure Python: tabloyu drop et (no-op if no query config)
"""
import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pyodbc
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from src.graphs.report_agent.subagents.text2sql.prompts import (
    QuerySchema,
    SQL_ARCHITECT_PROMPT,
)
from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql
from src.graphs.report_agent.subagents.text2sql.value_resolver_service import ValueResolverService
from src.graphs.report_agent.subagents.text2sql.business_rules_vector_store import BusinessRulesVectorStore

logger = logging.getLogger(__name__)

_db_executor = ThreadPoolExecutor(max_workers=3)
MAX_RETRY = 2


def _get_configurable(config: Optional[RunnableConfig], key: str, fallback):
    """RunnableConfig'ten değer oku; yoksa fallback döndür."""
    if not config:
        return fallback
    configurable = config.get("configurable", {})
    if hasattr(configurable, key):
        val = getattr(configurable, key)
    elif isinstance(configurable, dict):
        val = configurable.get(key)
    else:
        return fallback
    # Boş dict/string/None → fallback
    if val is None or val == "" or val == {}:
        return fallback
    return val


# =============================================================================
# DB UTILITY
# =============================================================================

def _serialize_row(columns: List[str], row: Any) -> Dict[str, Any]:
    """pyodbc Row → dict, Decimal güvenli."""
    record = {}
    for col, val in zip(columns, row):
        record[col] = float(val) if isinstance(val, Decimal) else val
    return record


def _parse_connection_string(connection_string: str) -> str:
    """mssql+pyodbc:// SQLAlchemy URL'sini pyodbc connection string'e çevir."""
    if not connection_string.startswith("mssql+pyodbc://"):
        return connection_string

    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(connection_string)
    query_params = parse_qs(parsed.query)
    driver = query_params.get("driver", ["ODBC Driver 17 for SQL Server"])[0]
    server = parsed.hostname
    if parsed.port:
        server = f"{server},{parsed.port}"
    return (
        f"Driver={{{driver}}};"
        f"Server={server};"
        f"Database={parsed.path.lstrip('/')};"
        f"UID={parsed.username};"
        f"PWD={parsed.password};"
        f"Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=30"
    )


async def _execute_sql_async(connection_string: str, sql: str) -> List[Dict[str, Any]]:
    """SQL'i thread pool'da async çalıştır."""
    pyodbc_conn_str = _parse_connection_string(connection_string)
    loop = asyncio.get_event_loop()

    def _run():
        conn = pyodbc.connect(pyodbc_conn_str, timeout=30)
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        return [_serialize_row(columns, row) for row in rows]

    return await loop.run_in_executor(_db_executor, _run)


# =============================================================================
# NODE 1: SQL ARCHITECT
# =============================================================================

def create_sql_architect_node(llm, column_metadata: Dict[str, Any]) -> Callable:
    """
    LLM (TEK ÇAĞRI): user_query + column_metadata + date_context + business_rules → QuerySchema.

    Tarih niyetini DateDescriptor olarak üretir (Python çözer).
    Business rule ID'lerini applied_rule_ids'e yazar (Python SQL'e ekler).
    Retry durumunda sql_error'ı alarak şemayı düzeltir.
    """
    structured_llm = llm.with_structured_output(QuerySchema)

    async def sql_architect_node(state: dict, *, config: RunnableConfig = None) -> dict:
        user_query = state.get("user_query", "")
        query_type = state.get("query_type", "SINGLE")
        business_rules_context = state.get("business_rules_context") or "Uygulanacak kural bulunamadı."
        active_sql = state.get("active_sql")
        active_filters = state.get("active_filters") or []
        sql_error = state.get("sql_error") or "Yok"

        # Runtime config'ten column_metadata override
        effective_metadata = _get_configurable(config, "column_metadata", column_metadata)

        # Tarih bağlamı
        today = date.today()

        # Konuşma bağlamı
        conversation_context = "Yeni sorgu, önceki bağlam yok."
        if active_sql:
            conversation_context = f"Önceki SQL: {active_sql[:300]}"
            if active_filters:
                filters_str = json.dumps(active_filters[:3], ensure_ascii=False)
                conversation_context += f"\nAktif filtreler: {filters_str}"

        prompt = SQL_ARCHITECT_PROMPT.format(
            user_query=user_query,
            query_type=query_type,
            today_date=today.isoformat(),
            current_year=today.year,
            current_month=today.month,
            current_quarter=(today.month - 1) // 3 + 1,
            column_metadata=json.dumps(effective_metadata, ensure_ascii=False, indent=2),
            business_rules_context=business_rules_context,
            conversation_context=conversation_context,
            sql_error=sql_error,
        )

        logger.info(f"[SQL_ARCHITECT] Planning: {user_query[:80]} (type={query_type})")
        schema: QuerySchema = await structured_llm.ainvoke(prompt)
        logger.info(
            f"[SQL_ARCHITECT] Schema: filters={len(schema.filters)}, "
            f"aggs={len(schema.aggregations)}, group_by={schema.group_by}, "
            f"limit={schema.limit}, rules={schema.applied_rule_ids}"
        )
        return {
            "query_schema": schema.model_dump(),
            "sql_error": None,  # Retry durumunda temizle
        }

    return sql_architect_node


# =============================================================================
# NODE 2: VALUE RESOLVER
# =============================================================================

def create_value_resolver_node(value_resolver: ValueResolverService) -> Callable:
    """
    Pure Python: QuerySchema.filters[].value_hint → resolved_value.
    Düşük confidence (< 75) → interrupt() ile kullanıcıya sor.
    """

    async def value_resolver_node(state: dict) -> dict:
        raw_schema = state.get("query_schema")
        if not raw_schema:
            return {}

        filters = raw_schema.get("filters", [])
        if not filters:
            return {}

        resolved_any = False

        for f in filters:
            column = f.get("column", "")
            value_hint = f.get("value_hint", "")

            # Atla: değer zaten çözülmüş, tarih, ya da boş
            if (
                f.get("resolved_value")
                or f.get("date_descriptor")
                or not value_hint
                or f.get("operator") in ("IS NULL", "IS NOT NULL")
            ):
                continue

            # Fuzzy match
            result = await value_resolver.resolve(value_hint, column)

            if not result:
                # Çözülemedi → kullanıcıya sor
                answer = interrupt({
                    "type": "input",
                    "question": f"'{value_hint}' değeri veritabanında bulunamadı. Lütfen tam değeri girin:",
                })
                f["resolved_value"] = answer
                resolved_any = True
                continue

            confidence = result.get("confidence", 0)
            candidate = result.get("resolved", "")

            if confidence >= 75:
                f["resolved_value"] = candidate
                f["resolution_confidence"] = confidence
                resolved_any = True
                logger.info(f"[VALUE_RESOLVER] '{value_hint}' → '{candidate}' (conf={confidence})")

            elif confidence >= 50:
                # Orta güven → onay iste
                answer = interrupt({
                    "type": "confirmation",
                    "question": f"'{value_hint}' için '{candidate}' mi kastetdiniz?",
                    "options": ["Evet", "Hayır, farklı bir değer girin"],
                })
                if answer == "Evet":
                    f["resolved_value"] = candidate
                    resolved_any = True
                else:
                    manual = interrupt({
                        "type": "input",
                        "question": f"'{value_hint}' için doğru değeri girin:",
                    })
                    f["resolved_value"] = manual
                    resolved_any = True

            else:
                # Düşük güven → direkt sor
                answer = interrupt({
                    "type": "input",
                    "question": f"'{value_hint}' değeri bulunamadı (en yakın: '{candidate}', %{confidence:.0f}). Lütfen tam değeri girin:",
                })
                f["resolved_value"] = answer
                resolved_any = True

        if resolved_any:
            return {"query_schema": raw_schema}
        return {}

    return value_resolver_node


# =============================================================================
# NODE 3: BUSINESS RULES
# =============================================================================

def _format_rule_sql_hint(sql: Dict[str, Any]) -> str:
    """Rule SQL bileşenlerini kısa okunabilir hint'e çevirir."""
    parts = []
    if sql.get("aggregation"):
        parts.append(f"AGG: {sql['aggregation'][:80]}")
    if sql.get("filter"):
        parts.append(f"FILTER: {sql['filter']}")
    if sql.get("group_by"):
        parts.append(f"GROUP_BY: {sql['group_by']}")
    if sql.get("having"):
        parts.append(f"HAVING: {sql['having']}")
    return " | ".join(parts) if parts else "(SQL bileşeni yok)"


def create_business_rules_node(vector_store: BusinessRulesVectorStore) -> Callable:
    """
    Pure Python: user_query → business_rules_context (LLM için ID + açıklama formatı).
    ChromaDB semantic search. sql_architect bu bağlamı okur, rule ID'lerini seçer.
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

        individual_rules = result.get("individual_rules", [])
        if not individual_rules:
            logger.info("[BUSINESS_RULES] No relevant rules found")
            return {"business_rules_context": "Uygulanacak kural bulunamadı."}

        # Individual rules formatı: LLM ID seçebilsin
        parts = []
        for rule in individual_rules:
            rule_id  = rule.get("id", "?")
            desc     = rule.get("description", "")
            is_def   = rule.get("is_default", False)
            sql_hint = _format_rule_sql_hint(rule.get("sql", {}))
            tag      = " [VARSAYILAN — HER ZAMAN UYGULA]" if is_def else ""
            parts.append(f"[{rule_id}]{tag}\n  Açıklama: {desc}\n  SQL: {sql_hint}")

        context = "\n\n".join(parts)
        logger.info(
            f"[BUSINESS_RULES] {result['total_count']} rules "
            f"({result['default_count']} default, {result['semantic_count']} semantic)"
        )
        return {"business_rules_context": context}

    return business_rules_node


# =============================================================================
# NODE 4: SQL GENERATOR
# =============================================================================

def create_sql_generator_node(
    default_table_name: str,
    full_rules_data: List[Dict[str, Any]],
) -> Callable:
    """
    Pure Python: QuerySchema → T-SQL. LLM kullanmaz.
    sql_builder.generate_sql'i çağırır.
    """

    async def sql_generator_node(state: dict, *, config: RunnableConfig = None) -> dict:
        raw_schema = state.get("query_schema")
        if not raw_schema:
            return {"error": "QuerySchema bulunamadı", "results": []}

        table_name = _get_configurable(config, "table_name", default_table_name)
        today = date.today()

        try:
            sql = generate_sql(raw_schema, table_name, full_rules_data, today)
            logger.info(f"[SQL_GENERATOR] SQL ready: {sql[:200]}")
            return {"sql_queries": [sql]}
        except Exception as e:
            logger.error(f"[SQL_GENERATOR] Build error: {e}")
            return {"error": f"SQL oluşturulamadı: {e}", "results": []}

    return sql_generator_node


# =============================================================================
# NODE 5: SQL EXECUTOR  (değişmez)
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


# =============================================================================
# NODE 0: CREATE TABLE  (graph START'tan önce)
# =============================================================================

def _execute_script_sync(connection_string: str, sql_script: str) -> None:
    """
    Multi-statement SQL scriptini senkron çalıştır.
    GO ile ayrılmış batch'leri sırayla execute eder.
    """
    pyodbc_conn_str = _parse_connection_string(connection_string)
    conn = pyodbc.connect(pyodbc_conn_str, autocommit=False)
    cursor = conn.cursor()
    try:
        batches = [b.strip() for b in sql_script.split("GO") if b.strip()]
        if not batches:
            batches = [sql_script]
        for batch in batches:
            cleaned = "\n".join(
                line for line in batch.splitlines()
                if line.strip() and not line.strip().startswith("--")
            )
            if cleaned:
                cursor.execute(cleaned)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def create_create_table_node(connection_string: str, default_table_name: str) -> Callable:
    """
    Pure Python: runtime config'ten query oku, tabloyu oluştur.
    query boşsa node'u geç (no-op).
    """

    async def create_table_node(state: dict, *, config: RunnableConfig = None) -> dict:
        query = _get_configurable(config, "query", "")
        if not query or not query.strip():
            logger.info("[CREATE_TABLE] No query in config, skipping table creation")
            return {}

        table_name = _get_configurable(config, "table_name", default_table_name)
        logger.info(f"[CREATE_TABLE] Creating table '{table_name}' ({len(query)} chars)")

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(_db_executor, _execute_script_sync, connection_string, query)
            logger.info(f"[CREATE_TABLE] '{table_name}' created successfully")
        except Exception as e:
            logger.error(f"[CREATE_TABLE] Error: {e}")
            return {"error": f"Tablo oluşturulamadı: {e}"}

        return {}

    return create_table_node


# =============================================================================
# NODE 6: CLEANUP TABLE  (graph END'den önce)
# =============================================================================

def create_cleanup_table_node(connection_string: str, default_table_name: str) -> Callable:
    """
    Pure Python: tabloyu DROP et.
    query config'te yoksa no-op.
    """

    async def cleanup_table_node(state: dict, *, config: RunnableConfig = None) -> dict:
        query = _get_configurable(config, "query", "")
        if not query or not query.strip():
            logger.info("[CLEANUP_TABLE] No query in config, skipping cleanup")
            return {}

        table_name = _get_configurable(config, "table_name", default_table_name)
        drop_sql = f"DROP TABLE IF EXISTS [{table_name}];"
        logger.info(f"[CLEANUP_TABLE] Dropping '{table_name}'")

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                _db_executor, _execute_script_sync, connection_string, drop_sql
            )
            logger.info(f"[CLEANUP_TABLE] '{table_name}' dropped")
        except Exception as e:
            logger.warning(f"[CLEANUP_TABLE] Drop failed (may not exist): {e}")
            # Hata state'e yazılmaz — cleanup başarısız olsa da akış devam eder

        return {}

    return cleanup_table_node
