"""
Text2SQL Subgraph Nodes (v3 — SemanticIntent Architecture)

NEW QUERY PIPELINE:
  business_rules       - BusinessRulesStore semantic search → auto_rules
  semantic_extractor   - LLM (SemanticIntent): user_query → entities/metrics/time
  term_resolver        - ChromaDB: entity/metric raw_texts → TermMatch map
  term_validator       - LLM gate: approves candidate_filter_terms
  schema_builder       - Python: SemanticIntent + TermMatch → QuerySchema (deterministic)
  value_resolver       - Python + DB: filter value_hint → resolved DB value
  sql_generator        - Pure Python: QuerySchema → T-SQL
  sql_executor         - pyodbc: T-SQL → results

MODIFY QUERY:
  modify_sql           - LLM: active_sql + modification request → modified SQL

Retry on sql_error → semantic_extractor (max MAX_RETRY times)
"""
import asyncio
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pyodbc
from langchain_core.runnables import RunnableConfig

from src.graphs.report_agent.subagents.text2sql.prompts import (
    QuerySchema,
    BusinessRulesValidationResult,
    TermValidationResult,
    BUSINESS_RULES_VALIDATOR_PROMPT,
    TERM_VALIDATOR_PROMPT,
    SEMANTIC_EXTRACTOR_PROMPT,
)
from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticIntent, TermMatch
from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql, _DATE_COLUMNS
from src.graphs.report_agent.subagents.text2sql.column_resolver import ColumnResolver
from src.graphs.report_agent.subagents.text2sql.value_resolver_service import ValueResolverService
from src.graphs.report_agent.subagents.text2sql.stores import BusinessRulesStore, TermStore

logger = logging.getLogger(__name__)

_db_executor = ThreadPoolExecutor(max_workers=3)

# Connection pool: pyodbc_conn_str -> pyodbc.Connection
_connection_pools: dict = {}
_pool_lock = threading.Lock()


def get_pooled_connection(pyodbc_conn_str: str):
    """
    Get or create a pooled connection for the given connection string.
    Connections are reused across calls to avoid reconnection overhead.
    """
    with _pool_lock:
        if pyodbc_conn_str in _connection_pools:
            conn = _connection_pools[pyodbc_conn_str]
            try:
                conn.execute("SELECT 1")
                return conn
            except Exception:
                logger.debug("[SQL_EXECUTOR] Pooled connection dead, reconnecting")
                try:
                    conn.close()
                except Exception:
                    pass
                del _connection_pools[pyodbc_conn_str]

        conn = pyodbc.connect(pyodbc_conn_str, timeout=30, autocommit=True)
        _connection_pools[pyodbc_conn_str] = conn
        logger.debug("[SQL_EXECUTOR] New pooled connection created")
        return conn


MAX_RETRY = 2
_MANUAL_ENTRY_OPTION = "Başka bir değer girin"

# --- HITL subgraph clarification cache key prefixes ---
# Her interrupt noktası için benzersiz prefix.
# Tam key = prefix + value/term string'i (ör. "vr_new_choice__istanbul")
_KEY_PREFIX_TERM            = "term__"
_KEY_PREFIX_VR_NEW_NF       = "vr_new_not_found__"
_KEY_PREFIX_VR_NEW_CHOICE   = "vr_new_choice__"
_KEY_PREFIX_VR_NEW_MANUAL   = "vr_new_manual__"
_KEY_PREFIX_VR_MOD_NF       = "vr_mod_not_found__"
_KEY_PREFIX_VR_MOD_CHOICE   = "vr_mod_choice__"
_KEY_PREFIX_VR_MOD_MANUAL   = "vr_mod_manual__"


def _get_cached_answer(answers: list | None, source_key: str) -> str | None:
    """text2sql_answers listesinde source_key'e ait cevabı döndürür. Yoksa None."""
    return next(
        (a["answer"] for a in (answers or []) if a["source"] == source_key),
        None,
    )


# Background table init state
_table_init_event = threading.Event()
_table_init_error: Optional[str] = "not_started"
_table_init_table_name: Optional[str] = None
_table_init_started = False  # Guard: background init only runs once
_table_init_lock = threading.Lock()  # Protects _table_init_started check-then-set
_table_verified: bool = False  # True = table confirmed in DB; reset on process restart
_verified_table_name: Optional[str] = None  # which table was verified


def _check_table_exists_in_db(pyodbc_conn_str: str, table_name: str) -> bool:
    """
    DB'de tablonun varlığını senkron olarak kontrol et.
    get_pooled_connection kullanır — run_in_executor ile çağrılır.
    """
    conn = get_pooled_connection(pyodbc_conn_str)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME = ? AND TABLE_TYPE = 'BASE TABLE'",
            table_name
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()  # connection pool'da kalır, kapatılmaz


def init_master_table_background(connection_string: str, table_name: str, sql_script: str) -> None:
    """
    Background thread: create master table at graph init time.
    Sets _table_init_event when done (success or failure).
    Only runs once per process lifetime (guarded by _table_init_started).
    """
    global _table_init_error, _table_init_table_name, _table_init_started, _table_verified, _verified_table_name
    with _table_init_lock:
        if _table_init_started:
            logger.info(f"[TABLE_INIT] Background init already started, skipping")
            return
        _table_init_started = True
    _table_init_table_name = table_name
    try:
        pyodbc_conn_str = _parse_connection_string(connection_string)
        if _check_table_exists_in_db(pyodbc_conn_str, table_name):
            logger.info(f"[TABLE_INIT] '{table_name}' already exists in DB, skipping creation")
            _table_init_error = None
            _table_verified = True
            _verified_table_name = table_name
            return
        logger.info(f"[TABLE_INIT] Background table creation started for '{table_name}'")
        _execute_script_sync(connection_string, sql_script)
        _table_init_error = None
        _table_verified = True
        _verified_table_name = table_name
        logger.info(f"[TABLE_INIT] Background table creation completed for '{table_name}'")
    except Exception as e:
        _table_init_error = str(e)
        logger.error(f"[TABLE_INIT] Background table creation failed: {e}")
    finally:
        _table_init_event.set()

# DocumentDate datetime kolonu için granülarite → SQL ifadeleri tablosu.
# TIME_SERIES_COMPARISON bloğu ve _normalize_document_date_group_by paylaşır.
_TIME_GRAN_MAP: dict = {
    "hourly":       ["CAST(DocumentDate AS DATE)", "DATEPART(HOUR, DocumentDate)"],
    "daily":        ["CAST(DocumentDate AS DATE)"],
    "weekly":       ["CONCAT(YEAR(DocumentDate), '-W', RIGHT('0' + CAST(DATEPART(WEEK, DocumentDate) AS VARCHAR), 2))"],
    "monthly":      ["CONCAT(YEAR(DocumentDate), '-', RIGHT('0' + CAST(MONTH(DocumentDate) AS VARCHAR), 2))"],
    "yearly":       ["YEAR(DocumentDate)"],
    # --- Aggregate period types (distribution, NOT time-series) ---
    "hour_of_day":  ["DATEPART(HOUR, DocumentDate)"],
    "day_of_week":  ["DATEPART(DW, DocumentDate)"],
    "day_of_month": ["DATEPART(DAY, DocumentDate)"],
}
# Aggregate period types: produce distribution data (bar chart), NOT time-series (line chart).
# Used by visualization layer to choose chart type.
AGGREGATE_PERIOD_GRANULARITIES: frozenset = frozenset({"hour_of_day", "day_of_week", "day_of_month"})

# Ham datetime kolon adları (GROUP BY'da kullanıldığında her timestamp ayrı grup olur)
_RAW_DATE_COL_NAMES = {"documentdate", "date"}

# Zaman-ilişkili tablo kolon adları — TIME_SERIES GROUP BY'da strip edilir.
# Bunlar SQL expression değil, tablo kolonları (LLM bazen ekstra ekler).
# Kontrol sırasında köşeli parantezler ve büyük/küçük harf normalize edilir.
_TIME_ADJACENT_COLS_UPPER = {
    "DAYOFWEEK", "DAYOFMONTH", "DAYOFYEAR", "WEEKDAY",
    "HOUR", "MINUTE", "SECOND",
    "WEEKNUM", "WEEKNUMBER", "MONTHNUMBER", "QUARTERNUMBER",
}

# Tüm olası zaman ifadeleri — redundant zaman kolonu tespiti için
# Hem eski (YEAR+MONTH ayrı) hem yeni (CONCAT birleşik) ifadeleri kapsar
_ALL_TIME_EXPRS_UPPER = {
    "CAST(DOCUMENTDATE AS DATE)",
    "YEAR(DOCUMENTDATE)",
    "MONTH(DOCUMENTDATE)",
    "DATEPART(WEEK, DOCUMENTDATE)",
    "DATEPART(WEEKDAY, DOCUMENTDATE)",
    "DATEPART(HOUR, DOCUMENTDATE)",
    "DATEPART(DW, DOCUMENTDATE)",          # NEW — day_of_week
    "DATEPART(DAY, DOCUMENTDATE)",          # NEW — day_of_month
    "HOUR",
    # Birleşik CONCAT ifadeleri (tek kolon üretir)
    "CONCAT(YEAR(DOCUMENTDATE), '-W', RIGHT('0' + CAST(DATEPART(WEEK, DOCUMENTDATE) AS VARCHAR), 2))",
    "CONCAT(YEAR(DOCUMENTDATE), '-', RIGHT('0' + CAST(MONTH(DOCUMENTDATE) AS VARCHAR), 2))",
}

# Business rule filter parse: [Column] = Value
_RULE_FILTER_EQ_RE = re.compile(r"^\[(\w+)\]\s*=\s*(.+)$")


def _detect_time_granularity_from_query(user_query: str) -> Optional[str]:
    """Detect time_granularity from Turkish keywords in user query (Option B fallback).

    Returns granularity string or None if no match.
    Order matters: aggregate-period patterns are checked FIRST (more specific),
    then time-series patterns (more general).
    """
    q = user_query.lower()

    # --- Aggregate period patterns (check first — more specific) ---
    if any(k in q for k in ("saate göre", "saatlere göre", "günün saatlerine göre", "saat dağılımı")):
        return "hour_of_day"
    if any(k in q for k in ("haftanın günlerine göre", "haftanın günleri", "günlere göre dağılım", "güne göre dağılım")):
        return "day_of_week"
    if any(k in q for k in ("ayın günlerine göre", "ayın günleri")):
        return "day_of_month"

    # --- Time-series patterns (existing — more general) ---
    if any(k in q for k in ("saatlik", "her saat", "saat saat", "saat bazında")):
        return "hourly"
    if any(k in q for k in ("haftalık", "her hafta", "hafta hafta", "hafta bazında")):
        return "weekly"
    if any(k in q for k in ("aylık", "her ay", "ay ay", "ay bazında")):
        return "monthly"
    if any(k in q for k in ("yıllık", "her yıl", "yıl yıl", "yıl bazında")):
        return "yearly"
    if any(k in q for k in ("günlük", "her gün", "gün gün", "gün bazında")):
        return "daily"

    return None


def _normalize_document_date_group_by(raw_schema: dict) -> dict:
    """
    GROUP BY içinde ham DocumentDate (datetime) kolonu varsa DATE ifadesine dönüştür.
    Ayrıca redundant zaman ifadelerini (YEAR+DATE gibi) tek granülariteye düşür.

    Neden: DocumentDate bir datetime kolonudur. Raw GROUP BY her timestamp'i ayrı grup
    yapar — "günlük ciro" gibi sorgularda tamamen yanlış sonuç üretir.

    time_granularity varsa → _TIME_GRAN_MAP'ten doğru ifadeyi kullan.
    Yoksa → CAST(DocumentDate AS DATE) varsayılan (en yaygın use case).

    Tüm query type'ları için çalışır. TIME_SERIES_COMPARISON kendi bloğunda
    group_by'ı zaten yönetir; bu normalizasyon ondan sonra kalan ham tarihleri temizler.
    """
    current = raw_schema.get("group_by", [])
    if not current:
        return raw_schema

    time_gran = raw_schema.get("time_granularity")
    time_exprs = _TIME_GRAN_MAP.get(time_gran, ["CAST(DocumentDate AS DATE)"])

    # Detect: raw DocumentDate OR mismatched/redundant time expressions
    has_raw_date = any(c.strip().strip("[]").lower() in _RAW_DATE_COL_NAMES for c in current)
    time_expr_hits = {c for c in current if c.upper() in _ALL_TIME_EXPRS_UPPER}
    expected_set = set(time_exprs)
    needs_fix = time_expr_hits and time_expr_hits != expected_set  # wrong or redundant time exprs

    if not has_raw_date and not needs_fix:
        return raw_schema  # no-op

    normalized: list = []
    time_added = False
    for col in current:
        if col.strip().strip("[]").lower() in _RAW_DATE_COL_NAMES or col.upper() in _ALL_TIME_EXPRS_UPPER:
            # Replace all time-related entries with the correct granularity (once)
            if not time_added:
                for expr in time_exprs:
                    if expr not in normalized:
                        normalized.append(expr)
                time_added = True
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
        logger.debug(f"[_get_configurable] No config, using fallback for '{key}' (fallback type={type(fallback).__name__}, len={len(fallback) if hasattr(fallback, '__len__') else 'N/A'})")
        return fallback
    configurable = config.get("configurable", {})
    if hasattr(configurable, key):
        val = getattr(configurable, key)
        logger.debug(f"[_get_configurable] Found '{key}' via getattr (type={type(val).__name__}, len={len(val) if hasattr(val, '__len__') else 'N/A'})")
    elif isinstance(configurable, dict):
        val = configurable.get(key)
        logger.debug(f"[_get_configurable] Dict lookup '{key}': found={val is not None}, val_type={type(val).__name__ if val is not None else 'None'}, len={len(val) if hasattr(val, '__len__') and val is not None else 'N/A'}")
    else:
        logger.debug(f"[_get_configurable] No match for '{key}', using fallback (configurable type={type(configurable).__name__})")
        return fallback
    # Boş dict/string/None → fallback
    if val is None or val == "" or val == {}:
        logger.debug(f"[_get_configurable] '{key}' is empty/None, using fallback (len={len(fallback) if hasattr(fallback, '__len__') else 'N/A'})")
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
    loop = asyncio.get_running_loop()

    def _run():
        conn = get_pooled_connection(pyodbc_conn_str)
        conn.timeout = 90  # pyodbc query timeout; cursor-level timeout doesn't exist
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        cursor.close()  # Close cursor, keep connection in pool
        return [_serialize_row(columns, row) for row in rows]

    return await loop.run_in_executor(_db_executor, _run)


# =============================================================================
# NODE 3: TERM RESOLVER
# =============================================================================

def create_term_resolver_node(
    term_vector_store: TermStore,
    column_resolver: Optional[ColumnResolver] = None,
) -> Callable:
    """
    Semantic term resolution + optional interrupt():

    NEW (semantic_intent present):
        Reads SemanticIntent.entities/metrics raw_texts, calls resolve_terms() in
        batch, converts results to term_resolution (raw_text → TermMatch dict) for
        schema_builder_node, and aggregates candidate_filter_terms for term_validator.

    LEGACY (no semantic_intent — backward compat):
        user_query → term_filters (Python-guaranteed WHERE filters)
                   + term_hints  (LLM advisory column name hints)

    Conflict resolution (legacy path): unambiguous high-specificity terms suppress
    ambiguous interrupts for the same column (e.g., 'ciro' suppresses 'ne kadar sattı').

    Args:
        term_vector_store: ChromaDB-backed term resolution store.
        column_resolver:   Optional ColumnResolver. When provided and a raw_text
                           has no ChromaDB match, resolves via alias table +
                           column_hint fallback. Applies to both entities and metrics.
    """

    def _resolver_output_to_term_match_dict(output) -> Optional[dict]:
        """
        Convert a TermResolverOutput to a TermMatch-compatible dict.

        Uses the first candidate_filter_terms entry to extract column_name and
        filter_structured. Returns None if the output has no resolved terms
        (empty candidate_filter_terms and no term_filters).
        """
        # Prefer candidate_filter_terms (richer data with column, filter_structured)
        if output.candidate_filter_terms:
            cft = output.candidate_filter_terms[0]
            return {
                "column_name": cft.get("column", ""),
                "filter_structured": cft.get("filter_structured"),
                "specificity": 1.0,
                "similarity": 1.0,
            }
        # Fall back to term_filters if no candidate_filter_terms
        if output.term_filters:
            tf = output.term_filters[0]
            return {
                "column_name": tf.get("column", ""),
                "filter_structured": {k: v for k, v in tf.items() if k != "logical_operator"},
                "specificity": 1.0,
                "similarity": 1.0,
            }
        return None

    async def term_resolver_node(state: dict) -> dict:
        # ── NEW PATH: SemanticIntent-based resolution ─────────────────────
        intent_dict = state.get("semantic_intent")
        if intent_dict:
            intent = SemanticIntent.model_validate(intent_dict)

            raw_texts: list[str] = (
                [e.raw_text for e in intent.entities]
                + [m.raw_text for m in intent.metrics]
            )

            resolved_map = term_vector_store.resolve_terms(raw_texts)
            # resolved_map: {raw_text → TermResolverOutput}

            term_resolution: dict = {}
            all_candidate_filter_terms: list = []

            for raw_text, output in resolved_map.items():
                # Aggregate candidate_filter_terms for term_validator
                all_candidate_filter_terms.extend(output.candidate_filter_terms)

                # Convert to TermMatch-compatible dict for schema_builder_node
                match_dict = _resolver_output_to_term_match_dict(output)
                if match_dict is not None:
                    term_resolution[raw_text] = match_dict

            # ColumnResolver fallback for unresolved raw_texts
            # Applies to all entity types AND metrics.
            if column_resolver is not None:
                # Entities: raw_text + optional column_hint
                for entity in intent.entities:
                    if entity.raw_text not in term_resolution:
                        resolved_col = column_resolver.resolve(
                            entity.raw_text, entity.column_hint
                        )
                        if resolved_col:
                            term_resolution[entity.raw_text] = {
                                "column_name": resolved_col,
                                "filter_structured": None,
                                "specificity": 0.5,
                                "similarity": 0.0,
                            }
                            logger.info(
                                f"[TERM_RESOLVER] resolver fallback (entity): "
                                f"'{entity.raw_text}' → '{resolved_col}'"
                            )

                # Metrics: raw_text only (no column_hint on SemanticMetric)
                for metric in intent.metrics:
                    if metric.raw_text not in term_resolution:
                        resolved_col = column_resolver.resolve(metric.raw_text)
                        if resolved_col:
                            term_resolution[metric.raw_text] = {
                                "column_name": resolved_col,
                                "filter_structured": None,
                                "specificity": 0.5,
                                "similarity": 0.0,
                            }
                            logger.info(
                                f"[TERM_RESOLVER] resolver fallback (metric): "
                                f"'{metric.raw_text}' → '{resolved_col}'"
                            )

            logger.info(
                f"[TERM_RESOLVER] semantic_intent path: "
                f"{len(raw_texts)} raw_text(s), "
                f"{len(term_resolution)} resolved, "
                f"{len(all_candidate_filter_terms)} filter candidate(s)"
            )
            return {
                "term_resolution":        term_resolution,
                "candidate_filter_terms": all_candidate_filter_terms,
            }

        # ── LEGACY PATH: raw user_query resolution ────────────────────────
        user_query = state.get("user_query", "")
        result = term_vector_store.resolve(user_query)

        term_filters = list(result.term_filters)
        metric_choice_hints: list[str] = []

        answers = state.get("text2sql_answers") or []

        # Source key is keyed on term string (not position): "term__<amb.term>"
        # result.ambiguous is sorted deterministically by (similarity * specificity) in _apply_conflict_resolution(),
        # so ordering is stable across identical queries. Even if order changed, cache lookup uses term string,
        # not position, so correctness is preserved (worst case: one extra re-run if non-deterministic order occurred).
        for amb in result.ambiguous:
            source_key = _KEY_PREFIX_TERM + amb.term
            option_labels = [
                f"{opt['column']}: {opt.get('description', '')}"
                for opt in amb.options
            ]
            cached = _get_cached_answer(answers, source_key)

            if cached is None:
                # Cevap yok → sinyal ver, subgraph'tan erken çık
                return {
                    "text2sql_clarification": {
                        "type": "choice",
                        "question": f'"{amb.term}" için hangi ölçütü kastetdiniz?',
                        "options": option_labels,
                        "source": source_key,
                    }
                }

            # Cevap var → işle
            answer = cached
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
        }

    return term_resolver_node


# =============================================================================
# NODE 3.5: TERM VALIDATOR (term_resolver ile PARALLEL çalışır)
# =============================================================================

def create_term_validator_node(llm) -> Callable:
    """LLM gate that validates candidate_filter_terms from term_resolver output."""
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

            answers_list = state.get("text2sql_answers") or []

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
                    source_nf = _KEY_PREFIX_VR_MOD_NF + embedded_val
                    cached_nf = _get_cached_answer(answers_list, source_nf)
                    if cached_nf is None:
                        return {
                            "text2sql_clarification": {
                                "type": "input",
                                "question": f"'{embedded_val}' veritabanında bulunamadı. Doğru değeri girin:",
                                "source": source_nf,
                            }
                        }
                    resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, cached_nf)
                    continue

                confidence = result.get("confidence", 0)
                candidate  = result.get("resolved", "")

                if confidence >= 75:
                    resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, candidate)
                    logger.info(
                        f"[VALUE_RESOLVER/MODIFY] '{embedded_val}' → '{candidate}' (conf={confidence})"
                    )
                else:
                    source_choice = _KEY_PREFIX_VR_MOD_CHOICE + embedded_val
                    cached_choice = _get_cached_answer(answers_list, source_choice)

                    if cached_choice is None:
                        label = candidate if confidence >= 50 else f"{candidate} (%{confidence:.0f} eşleşme)"
                        return {
                            "text2sql_clarification": {
                                "type": "choice",
                                "question": f"'{embedded_val}' için ne kullanılmalı?",
                                "options": [label, _MANUAL_ENTRY_OPTION],
                                "source": source_choice,
                            }
                        }

                    if cached_choice == _MANUAL_ENTRY_OPTION:
                        source_manual = _KEY_PREFIX_VR_MOD_MANUAL + embedded_val
                        cached_manual = _get_cached_answer(answers_list, source_manual)
                        if cached_manual is None:
                            return {
                                "text2sql_clarification": {
                                    "type": "input",
                                    "question": f"'{embedded_val}' için doğru değeri girin:",
                                    "source": source_manual,
                                }
                            }
                        resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, cached_manual)
                    else:
                        resolved_sql = _replace_in_sql(resolved_sql, column, embedded_val, cached_choice)

            return {"pre_built_sql": resolved_sql, "modification_hints": None}

        # ── NEW_QUERY BRANCH (mevcut, değişmez) ──────────────────────────────
        raw_schema = state.get("query_schema")
        if not raw_schema:
            return {}

        filters = raw_schema.get("filters", [])
        if not filters:
            return {}

        resolved_any = False

        answers = state.get("text2sql_answers") or []

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
                source_nf = _KEY_PREFIX_VR_NEW_NF + value_hint
                cached_nf = _get_cached_answer(answers, source_nf)
                if cached_nf is None:
                    return {
                        "text2sql_clarification": {
                            "type": "input",
                            "question": f"'{value_hint}' veritabanında bulunamadı. Lütfen tam adı girin:",
                            "source": source_nf,
                        }
                    }
                f["resolved_value"] = cached_nf
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
                source_choice = _KEY_PREFIX_VR_NEW_CHOICE + value_hint
                cached_choice = _get_cached_answer(answers, source_choice)

                if cached_choice is None:
                    label = candidate if confidence >= 50 else f"{candidate} (%{confidence:.0f} eşleşme)"
                    return {
                        "text2sql_clarification": {
                            "type": "choice",
                            "question": f"'{value_hint}' için ne kullanılmalı?",
                            "options": [label, _MANUAL_ENTRY_OPTION],
                            "source": source_choice,
                        }
                    }

                if cached_choice == _MANUAL_ENTRY_OPTION:
                    source_manual = _KEY_PREFIX_VR_NEW_MANUAL + value_hint
                    cached_manual = _get_cached_answer(answers, source_manual)
                    if cached_manual is None:
                        return {
                            "text2sql_clarification": {
                                "type": "input",
                                "question": f"'{value_hint}' için doğru değeri girin:",
                                "source": source_manual,
                            }
                        }
                    f["resolved_value"] = cached_manual
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

def create_business_rules_node(vector_store: BusinessRulesStore, llm=None) -> Callable:
    """
    Pure Python + optional LLM: user_query → state.auto_rules (resolved rule dicts).
    ChromaDB semantic search. llm sağlanırsa non-default aday kurallar
    LLM validation'dan geçirilir — çelişen kurallar filtrelenir.

    llm=None → backward compat, tüm kurallar direkt döner.
    """
    structured_llm = llm.with_structured_output(BusinessRulesValidationResult) if llm else None

    async def business_rules_node(state: dict) -> dict:
        user_query = state.get("user_query", "")

        loop = asyncio.get_running_loop()
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
# COMPARISON: Çakışan auto_rule filter'ları IN'e dönüştür
# =============================================================================

def _merge_conflicting_rule_filters_for_comparison(
    raw_schema: dict,
    auto_rules: list[dict],
) -> tuple[dict, list[dict]]:
    """
    COMPARISON sorgularında aynı kolona ait çakışan auto_rule filter'larını
    tespit eder, schema'ya tek IN filtresi olarak ekler ve rule'lardan kaldırır.

    Sadece basit [Column] = Value pattern'i eşleştirir; karmaşık ifadeler korunur.
    Orijinal listeleri mutate etmez — yeni kopyalar döner.
    """
    # Parse rule filters: column -> [(rule_index, value_str)]
    col_rule_map: dict[str, list[tuple[int, str]]] = {}
    for i, rule in enumerate(auto_rules):
        sql_filter = (rule.get("sql") or {}).get("filter") or ""
        m = _RULE_FILTER_EQ_RE.match(sql_filter.strip())
        if m:
            col, val = m.group(1), m.group(2).strip()
            col_rule_map.setdefault(col, []).append((i, val))

    # Çakışma var mı?
    conflicting_cols = {col: entries for col, entries in col_rule_map.items() if len(entries) > 1}
    if not conflicting_cols:
        return raw_schema, auto_rules

    # Kopyalar oluştur
    new_rules = list(auto_rules)
    schema_filters = list(raw_schema.get("filters") or [])

    for col, entries in conflicting_cols.items():
        vals = [e[1] for e in entries]

        # Schema'daki mevcut bu kolon filtrelerini kaldır (IN dahil — yenisiyle değişecek)
        schema_filters = [f for f in schema_filters if f.get("column") != col]

        # Yeni IN filtresi ekle
        schema_filters.append({
            "column": col,
            "operator": "IN",
            "values": vals,
            "logical_operator": "AND",
        })

        # Çakışan rule'ların filter'ını kaldır (diğer sql bileşenleri korunur)
        for idx, _ in entries:
            old_rule = new_rules[idx]
            new_sql = dict(old_rule.get("sql") or {})
            new_sql["filter"] = None
            new_rules[idx] = {**old_rule, "sql": new_sql}

        logger.info(
            f"[SQL_GENERATOR] COMPARISON: [{col}] çakışan rule filter'lar "
            f"IN ({vals}) olarak birleştirildi"
        )

    new_schema = {**raw_schema, "filters": schema_filters}
    return new_schema, new_rules


# =============================================================================
# NODE 4: SQL GENERATOR
# =============================================================================


def _sanitize_comparison_dimension(
    comp_dim: Optional[str],
    column_metadata: dict,
) -> tuple:
    """
    Validate and sanitize comparison_dimension from LLM output.

    Handles comma-separated values, bracket-wrapped names, empty strings.
    Returns (primary_dimension, extra_dimensions) tuple.
    """
    if not comp_dim or not comp_dim.strip():
        return None, []

    comp_dim = comp_dim.strip().strip("[]")

    if "," in comp_dim:
        parts = [p.strip().strip("[]") for p in comp_dim.split(",") if p.strip()]
        if not parts:
            return None, []
        primary = parts[0]
        extra = parts[1:]
    else:
        primary = comp_dim
        extra = []

    if column_metadata and primary not in column_metadata:
        logger.warning(
            f"[SQL_GENERATOR] comparison_dimension '{primary}' not in column_metadata, cleared"
        )
        return None, []

    if column_metadata:
        valid_extra = [e for e in extra if e in column_metadata]
        if len(valid_extra) < len(extra):
            dropped = [e for e in extra if e not in column_metadata]
            logger.warning(f"[SQL_GENERATOR] Dropped invalid extra dimensions: {dropped}")
        extra = valid_extra

    return primary, extra


def create_sql_generator_node(
    default_table_name: str,
    column_metadata: Optional[Dict[str, Any]] = None,
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
            return {"sql_queries": [pre_built_sql], "pre_built_sql": None, "time_granularity": None}

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
        # Ham tarih kolonları (DocumentDate) zaman ifadesiyle değiştirilmişse ORDER BY'dan kaldır
        # → _build_order_by otomatik olarak group_by'daki zaman ifadesini kullanır.
        if raw_schema.get("aggregations"):
            _order_col = raw_schema.get("order_by_column")
            if _order_col:
                # Ham tarih kolonu → her zaman kaldır (auto ORDER BY daha güvenli)
                if _order_col.strip().strip("[]").lower() in _RAW_DATE_COL_NAMES:
                    raw_schema = {**raw_schema, "order_by_column": None}
                    logger.warning(
                        f"[SQL_GENERATOR] order_by_column '{_order_col}' ham tarih kolonu "
                        f"→ kaldırıldı (auto ORDER BY devreye girer)"
                    )
                else:
                    _group_by_cols = raw_schema.get("group_by", [])
                    _agg_aliases = {_a.get("alias", "") for _a in raw_schema["aggregations"]}
                    # Tam eşleşme (substring değil — CONCAT içindeki kolon adı eşleşme sayılmaz)
                    _in_group_by = any(
                        _order_col.upper() == _gc.upper()
                        for _gc in _group_by_cols
                    )
                    if not _in_group_by and _order_col not in _agg_aliases:
                        raw_schema = {**raw_schema, "order_by_column": None}
                        logger.warning(
                            f"[SQL_GENERATOR] order_by_column '{_order_col}' GROUP BY veya "
                            f"aggregation alias'ta değil → kaldırıldı (auto ORDER BY devreye girer)"
                        )

        _time_gran = raw_schema.get("time_granularity")  # may be None for non-TIME_SERIES
        _comp_dim = None
        _extra_dims = []

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
                "platform": "DocumentKindName",
                "kanal":    "DocumentKindName",
                "kurye":    "DeliveryUserName",
                "masa":     "TableNo",
            }

            # --- Option A: Semantik alanlardan değerleri al ---
            # _time_gran zaten line ~1089'da initialize edildi (return için)
            _comp_dim_raw = raw_schema.get("comparison_dimension")
            _comp_dim, _extra_dims = _sanitize_comparison_dimension(
                _comp_dim_raw,
                column_metadata,
            )
            if _comp_dim != _comp_dim_raw:
                logger.info(
                    f"[SQL_GENERATOR] comparison_dimension sanitized: "
                    f"'{_comp_dim_raw}' → primary='{_comp_dim}', extra={_extra_dims}"
                )

            # --- Option B fallback: LLM alanları boş bıraktıysa query'den tespit ---
            _q_lower = (state.get("user_query") or "").lower()

            if not _time_gran:
                _time_gran = _detect_time_granularity_from_query(state.get("user_query", ""))
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
                # comp_dim her zaman başa gelir (zaten _existing'de olsa bile — _has_comp kontrolü
                # kaldırıldı: "zaten var → atla" mantığı carry-over loop'ta da dışlıyordu → drop bug)
                _new_group_by: list = []
                if _comp_dim:
                    _new_group_by.append(_comp_dim)
                _new_group_by.extend(_t_cols)
                # Add extra dimensions from comma-split
                for _ed in _extra_dims:
                    if _ed not in _new_group_by:
                        _new_group_by.append(_ed)
                # Mevcut group_by'dan TÜM zaman ifadelerini + zaman-ilişkili kolonları + entity'yi çıkar
                # (LLM bazen redundant YEAR+DATE veya DayOfWeek gibi alt-granülarite kolonları koyar)
                for _c in _existing:
                    _c_upper = _c.upper()
                    _c_clean = _c_upper.strip().strip("[]")
                    _is_time_expr = _c_upper in _ALL_TIME_EXPRS_UPPER
                    _is_time_col = _c_clean in _TIME_ADJACENT_COLS_UPPER
                    if not _is_time_expr and not _is_time_col and _c != _comp_dim and _c not in _extra_dims:
                        _new_group_by.append(_c)
                # order_by_column da kaldır — group_by yeniden inşa edildi,
                # eski order_by (örn. raw DocumentDate) artık geçersiz olabilir.
                # _build_order_by otomatik olarak group_by'daki zaman ifadesini kullanır.
                raw_schema = {**raw_schema, "group_by": _new_group_by, "order_by_column": None}
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

        # --- COMPARISON güvenlik ağı: çakışan auto_rule filtreleri → IN merge ---
        if state.get("query_type") == "COMPARISON" and auto_rules:
            raw_schema, auto_rules = _merge_conflicting_rule_filters_for_comparison(
                raw_schema, auto_rules
            )

        try:
            sql = generate_sql(raw_schema, table_name, auto_rules, today)
            logger.info(f"[SQL_GENERATOR] SQL ready: {sql[:200]}")
            return {
                "sql_queries": [sql],
                "time_granularity": _time_gran,
                "comparison_dimension": _comp_dim if state.get("query_type") == "TIME_SERIES_COMPARISON" else raw_schema.get("comparison_dimension"),
            }
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
# NODE: SEMANTIC EXTRACTOR
# =============================================================================

def create_semantic_extractor_node(llm) -> Callable:
    """
    LLM (STRUCTURED OUTPUT): user_query → SemanticIntent.

    Reads:  state["user_query"], state["query_type"], state.get("column_metadata", {}),
            state.get("messages", []), state.get("sql_error")
    Writes: {"semantic_intent": SemanticIntent.model_dump()}

    No SQL knowledge required — pure "what did the user want?" extraction.
    """
    structured_llm = llm.with_structured_output(SemanticIntent)

    async def semantic_extractor_node(state: dict) -> dict:
        user_query   = state.get("user_query", "")
        query_type   = state.get("query_type", "SINGLE")
        col_meta     = state.get("column_metadata") or {}
        messages     = state.get("messages") or []
        sql_error    = state.get("sql_error") or "Yok"

        column_names = ", ".join(col_meta.keys()) if col_meta else "Bilinmiyor"

        # Build conversation context from message history (last 3 pairs at most)
        if messages:
            last_msgs = messages[-6:]  # up to 3 human+ai pairs
            conv_lines = []
            for m in last_msgs:
                role = getattr(m, "type", None) or (m.get("role") if isinstance(m, dict) else "?")
                content = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else str(m))
                conv_lines.append(f"{role}: {content[:200]}")
            conversation_context = "\n".join(conv_lines)
        else:
            conversation_context = "Yeni konuşma, önceki bağlam yok."

        prompt = SEMANTIC_EXTRACTOR_PROMPT.format(
            user_query=user_query,
            query_type=query_type,
            column_names=column_names,
            conversation_context=conversation_context,
            sql_error=sql_error,
        )

        logger.info(f"[SEMANTIC_EXTRACTOR] Extracting intent: {user_query[:80]} (type={query_type})")
        result: SemanticIntent = await structured_llm.ainvoke(prompt)
        logger.info(
            f"[SEMANTIC_EXTRACTOR] entities={len(result.entities)}, "
            f"metrics={len(result.metrics)}, time={result.time}"
        )
        return {"semantic_intent": result.model_dump()}

    return semantic_extractor_node


# =============================================================================
# NODE: SCHEMA BUILDER
# =============================================================================

def create_schema_builder_node() -> Callable:
    """
    Pure Python: semantic_intent + term_resolution → QuerySchema.

    Reads:  state["semantic_intent"] (dict from SemanticIntent.model_dump()),
            state.get("term_resolution", {}) (dict of raw_text → TermMatch dict),
            state["query_type"], state.get("time_breakdown", False)
    Writes: {"query_schema": QuerySchema.model_dump()}

    No LLM involved. Deterministic conversion via build_query_schema().
    """

    async def schema_builder_node(state: dict) -> dict:
        intent_dict     = state.get("semantic_intent") or {}
        resolution_dict = state.get("term_resolution") or {}
        query_type      = state.get("query_type", "SINGLE")
        time_breakdown  = state.get("time_breakdown", False)
        today           = date.today()

        logger.info(
            f"[SCHEMA_BUILDER] INPUT: semantic_intent={bool(intent_dict)}, "
            f"term_resolution={len(resolution_dict)} terms, "
            f"query_type={query_type}, time_breakdown={time_breakdown}"
        )

        # Reconstruct SemanticIntent from dict
        intent = SemanticIntent.model_validate(intent_dict)

        # Reconstruct TermMatch objects from dict
        term_resolution_map: Dict[str, TermMatch] = {}
        for raw_text, tm_data in resolution_dict.items():
            if isinstance(tm_data, TermMatch):
                term_resolution_map[raw_text] = tm_data
            elif isinstance(tm_data, dict):
                term_resolution_map[raw_text] = TermMatch(
                    column_name=tm_data.get("column_name", raw_text),
                    filter_structured=tm_data.get("filter_structured"),
                    specificity=float(tm_data.get("specificity", 1.0)),
                    similarity=float(tm_data.get("similarity", 1.0)),
                )

        schema = build_query_schema(
            intent=intent,
            term_resolution=term_resolution_map,
            query_type=query_type,
            time_breakdown=time_breakdown,
            today=today,
        )

        logger.info(
            f"[SCHEMA_BUILDER] DECISION: filters={len(schema.filters)}, "
            f"group_by={schema.group_by}, gran={schema.time_granularity}"
        )
        logger.info(
            f"[SCHEMA_BUILDER] OUTPUT: query_schema ready, aggs={len(schema.aggregations)}"
        )
        return {"query_schema": schema.model_dump()}

    return schema_builder_node


# =============================================================================
# NODE 0: CREATE TABLE  (graph START'tan önce)
# =============================================================================

def _execute_script_sync(connection_string: str, sql_script: str) -> None:
    """
    Multi-statement SQL scriptini senkron çalıştır.
    GO ile ayrılmış batch'leri sırayla execute eder.
    """
    pyodbc_conn_str = _parse_connection_string(connection_string)
    conn = pyodbc.connect(pyodbc_conn_str, timeout=30, autocommit=False)
    conn.timeout = 120  # query execution timeout (seconds)
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
    DB-check-aware table creation node.

    Flow:
    1. _table_verified == True → skip (0 DB call)
    2. Background init hâlâ çalışıyorsa → bekle (max 180s)
    3. DB'de INFORMATION_SCHEMA.TABLES kontrolü
       - Var → _table_verified = True, skip
       - Yok → SQL script çalıştır, _table_verified = True
    """

    async def create_table_node(state: dict, *, config: RunnableConfig = None) -> dict:
        global _table_verified, _verified_table_name
        table_name = _get_configurable(config, "table_name", default_table_name)

        # --- Fast path: already verified this process lifetime for this table ---
        if _table_verified and _verified_table_name == table_name:
            logger.info(f"[CREATE_TABLE] '{table_name}' already verified, skipping")
            return {}

        # --- Wait for background init if still running ---
        if not _table_init_event.is_set():
            logger.info("[CREATE_TABLE] Waiting for background init to complete...")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _table_init_event.wait, 180)
            if not _table_init_event.is_set():
                logger.warning("[CREATE_TABLE] Background init timed out after 180s, proceeding")
                _table_init_event.set()

        # Background init may have set _table_verified — re-check before DB call
        if _table_verified and _verified_table_name == table_name:
            logger.info(f"[CREATE_TABLE] '{table_name}' verified by background init, skipping")
            return {}

        try:
            loop = asyncio.get_running_loop()
            pyodbc_conn_str = _parse_connection_string(connection_string)

            # --- DB existence check ---
            exists = await loop.run_in_executor(
                _db_executor, _check_table_exists_in_db, pyodbc_conn_str, table_name
            )
            if exists:
                _table_verified = True
                _verified_table_name = table_name
                logger.info(f"[CREATE_TABLE] '{table_name}' exists in DB, skipping creation")
                return {}

            # --- Table does not exist → create ---
            query = _get_configurable(config, "query", "")
            if not query or not query.strip():
                sql_file = Path(__file__).parent / "master_table_creation.sql"
                if sql_file.exists():
                    query = sql_file.read_text(encoding="utf-8")
                    logger.info(f"[CREATE_TABLE] Loaded SQL from file ({len(query)} chars)")
                else:
                    logger.warning("[CREATE_TABLE] No query available, skipping table creation")
                    return {}

            logger.info(f"[CREATE_TABLE] Creating table '{table_name}' ({len(query)} chars)")
            await loop.run_in_executor(_db_executor, _execute_script_sync, connection_string, query)
            _table_verified = True
            _verified_table_name = table_name
            logger.info(f"[CREATE_TABLE] '{table_name}' created successfully")
            return {}

        except Exception as e:
            logger.error(f"[CREATE_TABLE] Error: {e}")
            return {"error": f"Tablo kontrol/oluşturma hatası: {e}"}

    return create_table_node


# =============================================================================
# NODE 6: CLEANUP TABLE  (graph END'den önce)
# =============================================================================

def create_cleanup_table_node(connection_string: str, default_table_name: str) -> Callable:
    """No-op: table is permanent, no cleanup performed."""

    async def cleanup_table_node(state: dict, *, config: RunnableConfig = None) -> dict:
        return {}

    return cleanup_table_node
