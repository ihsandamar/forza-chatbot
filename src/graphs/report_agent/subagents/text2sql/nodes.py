"""
Text2SQL Subagent Nodes (v2)

8 node:
    create_table         - Pure Python: tablo oluştur (no-op if no query config)
    business_rules       - Pure Python + optional LLM: ChromaDB semantic search → auto_rules
                           (llm sağlanırsa non-default aday kurallar LLM ile validate edilir)
    term_resolver        - Pure Python + interrupt(): term_dict match → term_filters (guaranteed) + term_hints (LLM advisory)
    sql_architect        - LLM (STRUCTURED OUTPUT): user_query → QuerySchema (field mapping only)
    value_resolver       - Pure Python: fuzzy match + interrupt() if low confidence
    sql_generator        - Pure Python: QuerySchema + term_filters + auto_rules → T-SQL (NO LLM)
    sql_executor         - Pure Python: SQL çalıştır, hata → retry
    cleanup_table        - Pure Python: tabloyu drop et (no-op if no query config)
"""
import asyncio
import json
import logging
import re
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
    SchemaValidationResult,
    BusinessRulesValidationResult,
    TermValidationResult,
    SQL_ARCHITECT_PROMPT,
    SCHEMA_VALIDATOR_PROMPT,
    BUSINESS_RULES_VALIDATOR_PROMPT,
    TERM_VALIDATOR_PROMPT,
)
from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql, _DATE_COLUMNS
from src.graphs.report_agent.subagents.text2sql.value_resolver_service import ValueResolverService
from src.graphs.report_agent.subagents.text2sql.business_rules_vector_store import BusinessRulesVectorStore
from src.graphs.report_agent.subagents.text2sql.term_vector_store import TermVectorStore

logger = logging.getLogger(__name__)

_db_executor = ThreadPoolExecutor(max_workers=3)
MAX_RETRY = 2
_MANUAL_ENTRY_OPTION = "Başka bir değer girin"

# DocumentDate datetime kolonu için granülarite → SQL ifadeleri tablosu.
# TIME_SERIES_COMPARISON bloğu ve _normalize_document_date_group_by paylaşır.
_TIME_GRAN_MAP: dict = {
    "hourly":  ["CAST(DocumentDate AS DATE)", "Hour"],
    "daily":   ["CAST(DocumentDate AS DATE)"],
    "weekly":  ["YEAR(DocumentDate)", "DATEPART(WEEK, DocumentDate)"],
    "monthly": ["YEAR(DocumentDate)", "MONTH(DocumentDate)"],
    "yearly":  ["YEAR(DocumentDate)"],
}
# Ham datetime kolon adları (GROUP BY'da kullanıldığında her timestamp ayrı grup olur)
_RAW_DATE_COL_NAMES = {"documentdate", "date"}


def _normalize_document_date_group_by(raw_schema: dict) -> dict:
    """
    GROUP BY içinde ham DocumentDate (datetime) kolonu varsa DATE ifadesine dönüştür.

    Neden: DocumentDate bir datetime kolonudur. Raw GROUP BY her timestamp'i ayrı grup
    yapar — "günlük ciro" gibi sorgularda tamamen yanlış sonuç üretir.

    time_granularity varsa → _TIME_GRAN_MAP'ten doğru ifadeyi kullan.
    Yoksa → CAST(DocumentDate AS DATE) varsayılan (en yaygın use case).

    Tüm query type'ları için çalışır. TIME_SERIES_COMPARISON kendi bloğunda
    group_by'ı zaten yönetir; bu normalizasyon ondan sonra kalan ham tarihleri temizler.
    """
    current = raw_schema.get("group_by", [])
    has_raw_date = any(c.strip().strip("[]").lower() in _RAW_DATE_COL_NAMES for c in current)
    if not has_raw_date:
        return raw_schema  # no-op

    time_gran = raw_schema.get("time_granularity")
    time_exprs = _TIME_GRAN_MAP.get(time_gran, ["CAST(DocumentDate AS DATE)"])

    normalized: list = []
    for col in current:
        if col.strip().strip("[]").lower() in _RAW_DATE_COL_NAMES:
            for expr in time_exprs:
                if expr not in normalized:
                    normalized.append(expr)
        else:
            normalized.append(col)

    logger.info(f"[SQL_GENERATOR] DocumentDate normalize: {current} → {normalized} (gran={time_gran})")
    return {**raw_schema, "group_by": normalized}


def _replace_in_sql(sql: str, column: str, old_val: str, new_val: str) -> str:
    """
    pre_built_sql içindeki bir filtre değerini güvenli şekilde değiştirir.

    1. Kolon-aware pattern: [Column] = 'old_val' → [Column] = 'new_val'
    2. Fallback: plain case-insensitive replace (LLM köşeli parantez kullanmadıysa)
    """
    # 1. Column-aware replace (en güvenli)
    col_pattern = re.compile(
        rf"(\[{re.escape(column)}\]\s*=\s*)'{re.escape(old_val)}'",
        re.IGNORECASE,
    )
    result, n = col_pattern.subn(lambda m: f"{m.group(1)}'{new_val}'", sql)
    if n > 0:
        return result

    # 2. Fallback: plain replace (count=1 ile yanlış occurrence'ı engelle)
    plain_pattern = re.compile(rf"'{re.escape(old_val)}'", re.IGNORECASE)
    return plain_pattern.sub(lambda m: f"'{new_val}'", sql, count=1)


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
# NODE 3: TERM RESOLVER
# =============================================================================

def create_term_resolver_node(term_vector_store: TermVectorStore) -> Callable:
    """
    Semantic term resolution + optional interrupt():
    user_query → term_filters (Python-guaranteed WHERE filters)
               + term_hints  (LLM advisory column name hints)

    Conflict resolution: unambiguous high-specificity terms suppress ambiguous
    interrupts for the same column (e.g., 'ciro' suppresses 'ne kadar sattı').

    term_filters: sql_generator'da QuerySchema'ya merge edilir, LLM override edilir.
    term_hints:   sql_architect prompt'una inject edilir.
    """

    async def term_resolver_node(state: dict) -> dict:
        user_query = state.get("user_query", "")
        result = term_vector_store.resolve(user_query)

        term_filters = list(result.term_filters)
        metric_choice_hints: list[str] = []

        for amb in result.ambiguous:
            option_labels = [
                f"{opt['column']}: {opt.get('description', '')}"
                for opt in amb.options
            ]
            answer = interrupt({
                "type": "choice",
                "question": f'"{amb.term}" için hangi ölçütü kastetdiniz?',
                "options": option_labels,
            })
            for opt in amb.options:
                key = f"{opt['column']}: {opt.get('description', '')}"
                if key == answer:
                    if opt.get("filter_structured"):
                        fs = dict(opt["filter_structured"])
                        fs.setdefault("logical_operator", "AND")
                        term_filters.append(fs)
                    else:
                        chosen_col = opt["column"]
                        metric_choice_hints.append(
                            f'- Kullanıcı "{amb.term}" için [{chosen_col}] seçti '
                            f'→ aggregations: SUM([{chosen_col}]) kullan, başka kolon KULLANMA'
                        )
                        logger.info(
                            f"[TERM_RESOLVER] Ambiguous metric resolved: "
                            f"'{amb.term}' → '{chosen_col}' (user choice)"
                        )
                    break

        hints_text = result.hints_text
        if metric_choice_hints:
            hints_text += (
                "\n\n## KULLANICI METRİK KOLON SEÇİMİ (KESİNLİKLE UYGULA)\n"
                + "\n".join(metric_choice_hints)
                + "\n⚠️ Yukarıdaki kolon seçimi kullanıcı tarafından belirlendi — başka metric kolon kullanma!"
            )

        logger.info(
            f"[TERM_RESOLVER] {len(term_filters)} term_filter(s), "
            f"{len(metric_choice_hints)} metric choice(s)"
        )
        return {
            "term_filters":           term_filters,
            "candidate_filter_terms": result.candidate_filter_terms,
            "term_hints":             hints_text,
        }

    return term_resolver_node


# =============================================================================
# NODE 3.5: TERM VALIDATOR (term_resolver ile PARALLEL çalışır)
# =============================================================================

def create_term_validator_node(llm) -> Callable:
    """
    Parallel LLM gate: TermVectorStore'un ürettiği filter adaylarını doğrular.

    BusinessRulesValidationResult ile aynı pattern:
      - candidate_filter_terms'i state'ten okur (term_resolver üretir)
      - LLM her terimin kullanıcı tarafından gerçekten kastetilip kastetilmediğine karar verir
      - Onaylananlar → validated_term_filters (sql_generator bunu okur)
      - Reddedilenler → validated_term_filters'a GİRMEZ

    term_resolver, sql_architect, schema_validator ile PARALLEL çalışır.
    Latency: 0 — schema_merge zaten üç node'u bekler.
    """
    structured_llm = llm.with_structured_output(TermValidationResult)

    def _format_candidate_filters(candidate_filter_terms: list) -> str:
        """term_validator prompt için okunabilir format."""
        if not candidate_filter_terms:
            return "Aday filtre terimi yok."
        lines = []
        for cft in candidate_filter_terms:
            fs = cft.get("filter_structured") or {}
            col = fs.get("column", "?")
            op = fs.get("operator", "=")
            val = fs.get("value", "") or ""
            where_desc = f"{col} {op} {val}".strip()
            lines.append(
                f"  - ID: {cft.get('term_id', '?')}\n"
                f"    Terim: \"{cft['term']}\"\n"
                f"    Eklenecek WHERE: {where_desc}"
            )
        return "\n".join(lines)

    async def term_validator_node(state: dict) -> dict:
        user_query = state.get("user_query", "")
        candidate_filter_terms = state.get("candidate_filter_terms") or []

        # Aday yoksa → doğrulama atla, boş liste döndür
        if not candidate_filter_terms:
            logger.info("[TERM_VALIDATOR] No filter candidates, skipping validation")
            return {"validated_term_filters": []}

        candidate_filters_text = _format_candidate_filters(candidate_filter_terms)
        prompt = TERM_VALIDATOR_PROMPT.format(
            user_query=user_query,
            candidate_filters=candidate_filters_text,
        )

        logger.info(
            f"[TERM_VALIDATOR] Validating {len(candidate_filter_terms)} filter candidate(s) "
            f"for: {user_query[:80]}"
        )

        try:
            result: TermValidationResult = await structured_llm.ainvoke(prompt)
        except Exception as e:
            logger.error(f"[TERM_VALIDATOR] LLM error: {e} — returning empty validated_term_filters")
            return {"validated_term_filters": []}

        approved_ids = set(result.approved_filter_ids)
        validated_term_filters = [
            {**cft["filter_structured"], "logical_operator": "AND"}
            for cft in candidate_filter_terms
            if cft.get("term_id") in approved_ids and cft.get("filter_structured")
        ]

        logger.info(
            f"[TERM_VALIDATOR] {len(candidate_filter_terms)} candidates → "
            f"{len(validated_term_filters)} approved | approved_ids={result.approved_filter_ids} | "
            f"reasoning: {result.reasoning[:100]}"
        )
        return {"validated_term_filters": validated_term_filters}

    return term_validator_node


# =============================================================================
# NODE 1: SQL ARCHITECT
# =============================================================================

def create_sql_architect_node(llm, column_metadata: Dict[str, Any]) -> Callable:
    """
    LLM (STRUCTURED OUTPUT): user_query → QuerySchema (field mapping only).

    LLM sadece field mapping yapar:
      - Hangi kolon aggregate edilecek
      - Hangi kolon group by
      - Hangi filtreler (DateDescriptor ile tarihler)
    Business rules Python (sql_generator) tarafından auto_rules'dan uygulanır.
    """
    structured_llm = llm.with_structured_output(QuerySchema)

    async def sql_architect_node(state: dict, *, config: RunnableConfig = None) -> dict:
        user_query         = state.get("user_query", "")
        query_type         = state.get("query_type", "SINGLE")
        active_sql         = state.get("active_sql")
        active_filters     = state.get("active_filters") or []
        sql_error          = state.get("sql_error") or "Yok"
        effective_metadata = _get_configurable(config, "column_metadata", column_metadata)
        today              = date.today()

        # Konuşma bağlamı
        conversation_context = "Yeni sorgu, önceki bağlam yok."
        if active_sql:
            conversation_context = f"Önceki SQL: {active_sql[:300]}"
            if active_filters:
                conversation_context += f"\nAktif filtreler: {json.dumps(active_filters[:3], ensure_ascii=False)}"

        # Terim eşleştirme — term_resolver_node zaten state'e yazdı
        term_hints = state.get("term_hints") or "Özel terim eşleşmesi bulunamadı."

        prompt = SQL_ARCHITECT_PROMPT.format(
            term_hints=term_hints,
            user_query=user_query,
            query_type=query_type,
            today_date=today.isoformat(),
            current_year=today.year,
            current_month=today.month,
            current_quarter=(today.month - 1) // 3 + 1,
            column_metadata=json.dumps(effective_metadata, ensure_ascii=False, indent=2),
            conversation_context=conversation_context,
            sql_error=sql_error,
        )

        logger.info(f"[SQL_ARCHITECT] Planning: {user_query[:80]} (type={query_type})")
        schema: QuerySchema = await structured_llm.ainvoke(prompt)
        logger.info(
            f"[SQL_ARCHITECT] Schema: filters={len(schema.filters)}, "
            f"aggs={len(schema.aggregations)}, group_by={schema.group_by}, "
            f"limit={schema.limit}"
        )
        return {
            "query_schema": schema.model_dump(),
            "sql_error": None,
        }

    return sql_architect_node


# =============================================================================
# NODE 1.5: SCHEMA VALIDATOR (sql_architect ile PARALLEL çalışır)
# =============================================================================

def create_schema_validator_node(llm, column_metadata: Dict[str, Any]) -> Callable:
    """
    LLM (STRUCTURED OUTPUT): user_query → SchemaValidationResult.

    sql_architect ile paralel çalışır — architect çıktısını GÖRMEZ.
    Sadece GROUP BY, filters, limit üzerine bağımsız second-opinion üretir.
    merge_schemas node'u iki çıktıyı birleştirir.
    """
    structured_llm = llm.with_structured_output(SchemaValidationResult)

    async def schema_validator_node(state: dict, *, config: RunnableConfig = None) -> dict:
        user_query         = state.get("user_query", "")
        query_type         = state.get("query_type", "SINGLE")
        term_hints         = state.get("term_hints") or "Özel terim eşleşmesi bulunamadı."
        effective_metadata = _get_configurable(config, "column_metadata", column_metadata)
        today              = date.today()

        prompt = SCHEMA_VALIDATOR_PROMPT.format(
            user_query=user_query,
            query_type=query_type,
            today_date=today.isoformat(),
            current_year=today.year,
            current_month=today.month,
            current_quarter=(today.month - 1) // 3 + 1,
            column_metadata=json.dumps(effective_metadata, ensure_ascii=False, indent=2),
            term_hints=term_hints,
        )

        logger.info(f"[SCHEMA_VALIDATOR] Validating: {user_query[:80]} (type={query_type})")
        result: SchemaValidationResult = await structured_llm.ainvoke(prompt)
        logger.info(
            f"[SCHEMA_VALIDATOR] group_by={result.group_by}, "
            f"filters={len(result.filters)}, limit={result.limit} | {result.reasoning[:80]}"
        )
        return {"schema_validation": result.model_dump()}

    return schema_validator_node


# =============================================================================
# NODE 1.9: SCHEMA MERGE (fan-in: sql_architect + schema_validator + term_validator)
# =============================================================================

async def schema_merge_node(state: dict) -> dict:
    """
    Pure Python: sql_architect + schema_validator çıktılarını birleştir.

    Merge stratejisi:
      group_by  → validator otoritedir (kullanıcının gerçek niyetine bakar).
                  Validator boş döndürdüyse architect'inkini kullan.
      filters   → architect + validator'ın eksik bulduklarının union'ı.
                  Aynı column'dan sadece biri (architect öncelikli, validator ekler).
      limit     → validator setlendiyse kazanır, yoksa architect.
      diğerleri → architect çıktısı korunur (aggregations, order_by, select_columns).
    """
    arch_schema = state.get("query_schema")
    validation  = state.get("schema_validation")

    if not arch_schema:
        logger.warning("[SCHEMA_MERGE] No query_schema from architect, skipping merge")
        return {}

    if not validation:
        logger.warning("[SCHEMA_MERGE] No schema_validation, using architect output as-is")
        return {}

    # --- GROUP BY merge ---
    validator_group_by = validation.get("group_by") or []
    arch_group_by      = arch_schema.get("group_by") or []

    if validator_group_by:
        # Validator'ın listesi ana liste — architect'te olup validator'da olmayan kolonları düşür
        merged_group_by = list(validator_group_by)
        logger.info(
            f"[SCHEMA_MERGE] group_by: architect={arch_group_by} → validator={merged_group_by}"
        )
    else:
        # Validator boş döndü → architect'e güven
        merged_group_by = arch_group_by
        logger.info(f"[SCHEMA_MERGE] group_by: validator empty, keeping architect={merged_group_by}")

    # --- Filters merge ---
    arch_filters  = list(arch_schema.get("filters") or [])
    val_filters   = validation.get("filters") or []

    # Mevcut kolonları takip et (column bazlı dedup — architect öncelikli)
    existing_cols = {f.get("column") for f in arch_filters if f.get("column")}

    added = []
    for vf in val_filters:
        col = vf.get("column")
        if col and col not in existing_cols:
            arch_filters.append(vf)
            existing_cols.add(col)
            added.append(col)

    if added:
        logger.info(f"[SCHEMA_MERGE] filters: validator added missing columns: {added}")

    # --- Deduplication: aynı condition'ı iki kez ekleme ---
    # value_hint dahil edilir — COMPARISON sorgularında aynı kolon farklı
    # value_hint ile iki ayrı filtre olabilir (örn: dürümler OR içecek).
    seen_filter_keys: set = set()
    deduped_filters = []
    for f in arch_filters:
        key = (f.get("column"), f.get("operator"), f.get("value"), f.get("value_hint"))
        if key not in seen_filter_keys:
            deduped_filters.append(f)
            seen_filter_keys.add(key)
    arch_filters = deduped_filters

    # --- Limit merge ---
    val_limit  = validation.get("limit")
    arch_limit = arch_schema.get("limit")
    merged_limit = val_limit if val_limit is not None else arch_limit

    if val_limit is not None and val_limit != arch_limit:
        logger.info(f"[SCHEMA_MERGE] limit: validator={val_limit} overrides architect={arch_limit}")

    # --- Birleştir ---
    merged_schema = {
        **arch_schema,
        "group_by": merged_group_by,
        "filters":  arch_filters,
        "limit":    merged_limit,
    }

    logger.info(
        f"[SCHEMA_MERGE] Final: group_by={merged_group_by}, "
        f"filters={len(arch_filters)}, limit={merged_limit}"
    )
    return {"query_schema": merged_schema}


# =============================================================================
# NODE 2: VALUE RESOLVER
# =============================================================================

def create_value_resolver_node(value_resolver: ValueResolverService) -> Callable:
    """
    Pure Python: QuerySchema.filters[].value_hint → resolved_value.
    Düşük confidence (< 75) → interrupt() ile kullanıcıya sor.
    """

    async def value_resolver_node(state: dict) -> dict:
        pre_built_sql      = state.get("pre_built_sql")
        modification_hints = state.get("modification_hints") or []

        # ── MODIFY_QUERY BRANCH ───────────────────────────────────────────────
        if pre_built_sql and modification_hints:
            resolved_sql = pre_built_sql

            for hint in modification_hints:
                column       = hint.get("column", "")
                embedded_val = hint.get("embedded_value", "")

                if not embedded_val:
                    continue

                # Tarih ve saf sayıları atla
                if re.match(r"^[\d.,]+$", embedded_val) or re.search(r"\d{4}-\d{2}-\d{2}", embedded_val):
                    logger.debug(f"[VALUE_RESOLVER/MODIFY] Atlandı (tarih/sayı): '{embedded_val}'")
                    continue

                result = await value_resolver.resolve(embedded_val, column)

                if not result:
                    answer = interrupt({
                        "type": "input",
                        "question": f"'{embedded_val}' veritabanında bulunamadı. Doğru değeri girin:",
                    })
                    resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, answer)
                    continue

                confidence = result.get("confidence", 0)
                candidate  = result.get("resolved", "")

                if confidence >= 75:
                    resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, candidate)
                    logger.info(
                        f"[VALUE_RESOLVER/MODIFY] '{embedded_val}' → '{candidate}' (conf={confidence})"
                    )
                else:
                    label = candidate if confidence >= 50 else f"{candidate} (%{confidence:.0f} eşleşme)"
                    answer = interrupt({
                        "type": "choice",
                        "question": f"'{embedded_val}' için ne kullanılmalı?",
                        "options": [label, _MANUAL_ENTRY_OPTION],
                    })
                    if answer == _MANUAL_ENTRY_OPTION:
                        answer = interrupt({
                            "type": "input",
                            "question": f"'{embedded_val}' için doğru değeri girin:",
                        })
                    resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, answer)

            return {"pre_built_sql": resolved_sql, "modification_hints": None}

        # ── NEW_QUERY BRANCH (mevcut, değişmez) ──────────────────────────────
        raw_schema = state.get("query_schema")
        if not raw_schema:
            return {}

        filters = raw_schema.get("filters", [])
        if not filters:
            return {}

        resolved_any = False

        for f in filters:
            column     = f.get("column", "")
            value_hint = f.get("value_hint", "")

            if (
                f.get("resolved_value")
                or f.get("date_descriptor")
                or not value_hint
                or f.get("operator") in ("IS NULL", "IS NOT NULL")
            ):
                continue

            result = await value_resolver.resolve(value_hint, column)

            if not result:
                answer = interrupt({
                    "type": "input",
                    "question": f"'{value_hint}' veritabanında bulunamadı. Lütfen tam adı girin:",
                })
                f["resolved_value"] = answer
                resolved_any = True
                continue

            confidence = result.get("confidence", 0)
            candidate  = result.get("resolved", "")

            if confidence >= 75:
                f["resolved_value"] = candidate
                f["resolution_confidence"] = confidence
                resolved_any = True
                logger.info(f"[VALUE_RESOLVER] '{value_hint}' → '{candidate}' (conf={confidence})")
            else:
                label = candidate if confidence >= 50 else f"{candidate} (%{confidence:.0f} eşleşme)"
                answer = interrupt({
                    "type": "choice",
                    "question": f"'{value_hint}' için ne kullanılmalı?",
                    "options": [label, _MANUAL_ENTRY_OPTION],
                })
                if answer == _MANUAL_ENTRY_OPTION:
                    manual = interrupt({
                        "type": "input",
                        "question": f"'{value_hint}' için doğru değeri girin:",
                    })
                    f["resolved_value"] = manual
                    f["resolution_confidence"] = 100
                else:
                    f["resolved_value"] = candidate
                    f["resolution_confidence"] = confidence
                    logger.info(
                        f"[VALUE_RESOLVER] '{value_hint}' → '{candidate}' (user_selected, conf={confidence})"
                    )
                resolved_any = True

        if resolved_any:
            return {"query_schema": raw_schema}
        return {}

    return value_resolver_node


# =============================================================================
# NODE 3: BUSINESS RULES
# =============================================================================

def create_business_rules_node(vector_store: BusinessRulesVectorStore, llm=None) -> Callable:
    """
    Pure Python + optional LLM: user_query → state.auto_rules (resolved rule dicts).
    ChromaDB semantic search. llm sağlanırsa non-default aday kurallar
    LLM validation'dan geçirilir — çelişen kurallar filtrelenir.

    llm=None → backward compat, tüm kurallar direkt döner.
    """
    structured_llm = llm.with_structured_output(BusinessRulesValidationResult) if llm else None

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

        # --- LLM validation: default kurallar her zaman, aday kurallar LLM filtreler ---
        if structured_llm:
            default_rules    = [r for r in individual_rules if r.get("is_default", False)]
            candidate_rules  = [r for r in individual_rules if not r.get("is_default", False)]

            if candidate_rules:
                candidate_descriptions = "\n".join([
                    f"- ID: \"{r['id']}\"\n  Açıklama: {r['description']}"
                    for r in candidate_rules
                ])
                prompt = BUSINESS_RULES_VALIDATOR_PROMPT.format(
                    user_query=user_query,
                    candidate_rules=candidate_descriptions,
                )
                validation: BusinessRulesValidationResult = await structured_llm.ainvoke(prompt)
                confirmed_ids        = set(validation.applicable_rule_ids)
                confirmed_candidates = [r for r in candidate_rules if r["id"] in confirmed_ids]

                logger.info(
                    f"[BUSINESS_RULES] LLM validation: "
                    f"{len(candidate_rules)} candidates → {len(confirmed_candidates)} confirmed "
                    f"({list(confirmed_ids) or 'none'}). Reasoning: {validation.reasoning[:80]}"
                )
                individual_rules = default_rules + confirmed_candidates
            else:
                individual_rules = default_rules

        logger.info(
            f"[BUSINESS_RULES] {result['total_count']} rules "
            f"({result['default_count']} default, {result['semantic_count']} semantic)"
            f" → {len(individual_rules)} final"
        )
        return {"auto_rules": individual_rules}

    return business_rules_node


# =============================================================================
# NODE 4: SQL GENERATOR
# =============================================================================

def create_sql_generator_node(
    default_table_name: str,
) -> Callable:
    """
    Pure Python: QuerySchema + state.auto_rules + state.term_filters → T-SQL. LLM kullanmaz.

    term_filters: term_resolver tarafından Python-garantili üretilmiş WHERE filtreler.
    Eğer term_filters ile LLM'in ürettiği QuerySchema'da aynı kolon varsa → term_filter WINS.
    """

    async def sql_generator_node(state: dict, *, config: RunnableConfig = None) -> dict:
        # MODIFY_QUERY bypass: modify_sql node zaten doğru SQL ürettiyse yeniden üretme.
        # pre_built_sql, sql_executor'dan sonra None'a resetlenir (her turda classify_intent temizler).
        pre_built_sql = state.get("pre_built_sql")
        if pre_built_sql:
            logger.info(f"[SQL_GENERATOR] pre_built_sql mevcut, SQL üretimi atlanıyor: {pre_built_sql[:120]}")
            return {"sql_queries": [pre_built_sql], "pre_built_sql": None}

        raw_schema = state.get("query_schema")
        if not raw_schema:
            return {"error": "QuerySchema bulunamadı", "results": []}

        table_name   = _get_configurable(config, "table_name", default_table_name)
        auto_rules   = state.get("auto_rules") or []
        validated_term_filters = state.get("validated_term_filters")
        # validated_term_filters is None when term_validator hasn't run (e.g., crashed).
        # Fall back to [] — not to raw term_filters — to avoid false positive WHERE filters.
        term_filters = validated_term_filters if validated_term_filters is not None else []
        if validated_term_filters is None:
            logger.warning(
                "[SQL_GENERATOR] validated_term_filters is None — term_validator may not have run. "
                "Using empty list (LLM handles filters via prompts)."
            )
        today        = date.today()

        # --- COMPARISON güvenlik ağı 1: limit=1 ASLA geçemez ---
        # LLM RANKING kuralını yanlışlıkla uygulayıp limit=1 set edebilir.
        # COMPARISON'da tüm karşılaştırılan varlıklar dönmeli — TOP 1 birini gizler.
        if state.get("query_type") == "COMPARISON" and raw_schema.get("limit") == 1:
            raw_schema = {**raw_schema, "limit": None}
            logger.warning("[SQL_GENERATOR] COMPARISON query: limit=1 LLM hatası düzeltildi → None")

        # --- COMPARISON güvenlik ağı 2: tarih filtresi yoksa bu ayı ekle ---
        # Kullanıcı tarih belirtmeden "A ve B'yi karşılaştır" dediğinde default = bu ay.
        if state.get("query_type") == "COMPARISON":
            existing_filters = raw_schema.get("filters", [])
            has_date_filter = any(
                f.get("date_descriptor") or f.get("column") in _DATE_COLUMNS
                for f in existing_filters
            )
            if not has_date_filter:
                this_month_filter = {
                    "column": "DocumentDate",
                    "operator": ">=",
                    "date_descriptor": {"type": "current_period", "period": "month"},
                    "logical_operator": "AND",
                }
                raw_schema = {**raw_schema, "filters": list(existing_filters) + [this_month_filter]}
                logger.info("[SQL_GENERATOR] COMPARISON: tarih filtresi yok → bu ay eklendi")

        # --- Genel güvenlik ağı: aynı kolondaki AND = filtreleri → IN ---
        # "CategoryName = 'A' AND CategoryName = 'B'" imkansız koşul — IN('A','B')'e çevir.
        _filters = list(raw_schema.get("filters", []))
        _col_eq_groups: dict = {}
        for _f in _filters:
            if (
                _f.get("operator") == "="
                and (_f.get("logical_operator") or "AND").upper() == "AND"
                and not _f.get("date_descriptor")
            ):
                _c = _f.get("column", "")
                if _c:
                    _col_eq_groups.setdefault(_c, []).append(_f)
        if any(len(_g) > 1 for _g in _col_eq_groups.values()):
            _merged_cols: set = set()
            _new_filters: list = []
            for _f in _filters:
                _c = _f.get("column", "")
                _group = _col_eq_groups.get(_c, [])
                if len(_group) > 1 and _c not in _merged_cols:
                    _vals = [
                        _fi.get("resolved_value") or _fi.get("value", "")
                        for _fi in _group
                        if _fi.get("resolved_value") or _fi.get("value")
                    ]
                    if _vals:
                        _mf = {**_group[0], "operator": "IN", "values": _vals}
                        _mf.pop("value", None)
                        _mf.pop("resolved_value", None)
                        _new_filters.append(_mf)
                        _merged_cols.add(_c)
                        logger.info(
                            f"[SQL_GENERATOR] Aynı kolon AND = filtreleri IN'e çevrildi: {_c} IN {_vals}"
                        )
                elif _c in _merged_cols and len(_group) > 1:
                    pass  # zaten birleştirildi, atla
                else:
                    _new_filters.append(_f)
            raw_schema = {**raw_schema, "filters": _new_filters}

        # --- Aggregation güvenlik ağı: order_by_column GROUP BY veya alias'ta yoksa kaldır ---
        # GROUP BY sorgusunda ORDER BY kolonu GROUP BY veya aggregation alias'ında olmalı.
        if raw_schema.get("aggregations"):
            _order_col = raw_schema.get("order_by_column")
            if _order_col:
                _group_by_cols = raw_schema.get("group_by", [])
                _agg_aliases = {_a.get("alias", "") for _a in raw_schema["aggregations"]}
                _in_group_by = any(
                    _order_col.upper() == _gc.upper() or _order_col.upper() in _gc.upper()
                    for _gc in _group_by_cols
                )
                if not _in_group_by and _order_col not in _agg_aliases:
                    raw_schema = {**raw_schema, "order_by_column": None}
                    logger.warning(
                        f"[SQL_GENERATOR] order_by_column '{_order_col}' GROUP BY veya "
                        f"aggregation alias'ta değil → kaldırıldı (auto ORDER BY devreye girer)"
                    )

        # --- TIME_SERIES_COMPARISON güvenlik ağı: semantik alanlardan GROUP BY inşa et ---
        # Önce QuerySchema.time_granularity + comparison_dimension kullan (Option A).
        # LLM alanları boş bıraktıysa kullanıcı query'sinden keyword matching ile tespit (Option B).
        if state.get("query_type") == "TIME_SERIES_COMPARISON":
            # _TIME_GRAN_MAP module-level constant'ta tanımlı (bu dosya başı)
            # Entity keyword root → DB kolon adı (Türkçe kök eşleştirme — fallback için)
            _ENTITY_ROOTS: dict = {
                "ürün":     "ProductName",
                "şube":     "BranchName",
                "kategori": "CategoryName",
                "müşteri":  "CustomerName",
                "cari":     "CustomerName",
                "kasiyer":  "CashierName",
                "şehir":    "BranchCityName",
                "kanal":    "DocumentKindName",
                "kurye":    "DeliveryUserName",
                "masa":     "TableNo",
            }

            # --- Option A: Semantik alanlardan değerleri al ---
            _time_gran = raw_schema.get("time_granularity")
            _comp_dim  = raw_schema.get("comparison_dimension")

            # --- Option B fallback: LLM alanları boş bıraktıysa query'den tespit ---
            _q_lower = (state.get("user_query") or "").lower()

            if not _time_gran:
                if any(_k in _q_lower for _k in ("saatlik", "her saat", "saat saat", "saat bazında")):
                    _time_gran = "hourly"
                elif any(_k in _q_lower for _k in ("haftalık", "her hafta", "hafta hafta", "hafta bazında")):
                    _time_gran = "weekly"
                elif any(_k in _q_lower for _k in ("aylık", "her ay", "ay ay", "ay bazında")):
                    _time_gran = "monthly"
                elif any(_k in _q_lower for _k in ("yıllık", "her yıl", "yıl yıl", "yıl bazında")):
                    _time_gran = "yearly"
                elif any(_k in _q_lower for _k in ("günlük", "her gün", "gün gün", "gün bazında")):
                    _time_gran = "daily"
                if _time_gran:
                    logger.warning(f"[SQL_GENERATOR] TIME_SERIES: time_granularity keyword fallback: {_time_gran}")

            if not _comp_dim:
                for _root, _col in _ENTITY_ROOTS.items():
                    if _root in _q_lower:
                        _comp_dim = _col
                        logger.warning(f"[SQL_GENERATOR] TIME_SERIES: comparison_dimension keyword fallback: {_root}→{_col}")
                        break

            # --- GROUP BY inşası ---
            if _time_gran or _comp_dim:
                _t_cols    = _TIME_GRAN_MAP.get(_time_gran, []) if _time_gran else []
                _raw_dates = {"DocumentDate", "Date"}
                # Mevcut group_by'dan ham tarih kolonlarını çıkar
                _existing  = [_c for _c in raw_schema.get("group_by", []) if _c not in _raw_dates]
                _time_set  = set(_t_cols)
                # comp_dim her zaman başa gelir (zaten _existing'de olsa bile — _has_comp kontrolü
                # kaldırıldı: "zaten var → atla" mantığı carry-over loop'ta da dışlıyordu → drop bug)
                _new_group_by: list = []
                if _comp_dim:
                    _new_group_by.append(_comp_dim)
                _new_group_by.extend(_t_cols)
                # Mevcut group_by'dan zaman ifadeleri + entity dışındaki kolonları koru
                for _c in _existing:
                    if _c not in _time_set and _c != _comp_dim:
                        _new_group_by.append(_c)
                raw_schema = {**raw_schema, "group_by": _new_group_by}
                logger.info(
                    f"[SQL_GENERATOR] TIME_SERIES group_by inşa edildi: "
                    f"entity={_comp_dim}, gran={_time_gran}, result={_new_group_by}"
                )

        # --- DocumentDate datetime güvenlik ağı (tüm query type'lar) ---
        # TIME_SERIES bloğu kendi group_by'ını halleder; bu adım kalan
        # ham DocumentDate'leri (RANKING, SINGLE, COMPARISON) temizler.
        raw_schema = _normalize_document_date_group_by(raw_schema)

        # --- term_filters merge: Python garantili filtreler LLM'i override eder ---
        if term_filters:
            schema_filters = list(raw_schema.get("filters", []))
            override_cols  = {tf["column"] for tf in term_filters}
            # Aynı kolondaki LLM filterlerini kaldır
            schema_filters = [f for f in schema_filters if f.get("column") not in override_cols]
            # Garantili filtreleri ekle
            schema_filters.extend(term_filters)
            raw_schema = {**raw_schema, "filters": schema_filters}
            logger.info(
                f"[SQL_GENERATOR] validated_term_filters merged: {[tf['column'] for tf in term_filters]}"
            )

        try:
            sql = generate_sql(raw_schema, table_name, auto_rules, today)
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
