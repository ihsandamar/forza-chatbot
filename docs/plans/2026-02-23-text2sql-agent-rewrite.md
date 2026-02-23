# Text2SQL Agent Rewrite Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `report_agent/text2sql` subagent'ını tek LLM çağrısı + deterministik Python SQL generator ile yeniden yaz.

**Architecture:** `business_rules → sql_architect (LLM) → value_resolver → sql_generator (Python) → sql_executor`. LLM sadece QuerySchema üretir; tarih çözme ve SQL yazma tamamen Python'da.

**Tech Stack:** LangGraph, Pydantic v2, pyodbc, rapidfuzz, chromadb, Python 3.12

**Design Doc:** `docs/plans/2026-02-23-text2sql-redesign.md`

---

## Referans Dosyalar

Değiştirilecek:
- `src/graphs/report_agent/subagents/text2sql/state.py`
- `src/graphs/report_agent/subagents/text2sql/prompts.py`
- `src/graphs/report_agent/subagents/text2sql/nodes.py`
- `src/graphs/report_agent/subagents/text2sql/graph.py`

Yeni:
- `src/graphs/report_agent/subagents/text2sql/sql_builder.py`

---

## Task 1: state.py — query_plan → query_schema

**File:** `src/graphs/report_agent/subagents/text2sql/state.py`

Tek değişiklik: `query_plan` field'ını `query_schema` olarak yeniden adlandır.

**Step 1: Dosyayı tamamen yeniden yaz**

```python
from typing import Any, Dict, List, Optional, TypedDict


class Text2SQLState(TypedDict, total=False):
    """
    Text2SQL subagent state.

    Overlapping keys (LangGraph otomatik parent ReportState ile sync eder):
        user_query, query_type, active_sql, active_filters,
        sql_queries, results, error, active_results

    Internal keys (sadece bu subgraph içinde kullanılır):
        query_schema, business_rules_context, retry_count, sql_error
    """

    # --- ReportState overlapping ---
    user_query: str
    query_type: Optional[str]
    active_sql: Optional[str]
    active_filters: Optional[List[Dict[str, Any]]]
    sql_queries: Optional[List[str]]
    results: Optional[List[Dict[str, Any]]]
    error: Optional[str]
    active_results: Optional[List[Dict[str, Any]]]

    # --- Internal ---
    query_schema: Optional[Dict[str, Any]]     # QuerySchema.model_dump()
    business_rules_context: Optional[str]      # LLM için formatlı kural listesi
    retry_count: int                           # 0 | 1 | 2
    sql_error: Optional[str]                   # Son SQL hata mesajı (retry için)
```

**Step 2: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/state.py
git commit -m "refactor(text2sql): rename query_plan → query_schema in state"
```

---

## Task 2: prompts.py — Yeni modeller + SQL_ARCHITECT_PROMPT

**File:** `src/graphs/report_agent/subagents/text2sql/prompts.py`

Eski modeller (`QueryPlan`, `QueryFilter`, `QueryAggregation`, `GeneratedSQL`, `FixedSQL`) kaldırılır. Yeni modeller + tek prompt eklenir.

**Step 1: Dosyayı tamamen yeniden yaz**

```python
from typing import List, Literal, Optional

from pydantic import BaseModel


# =============================================================================
# PYDANTIC MODELS — sql_architect node'unun structured output'u
# =============================================================================

class DateDescriptor(BaseModel):
    """
    LLM tarih niyetini yapısal olarak yazar; Python DATEADD/YEAR/CAST'e çevirir.

    Örnekler:
      "son 3 ay"  → type=relative, unit=month, amount=-3
      "bu yıl"    → type=current_period, period=year
      "15 ocak"   → type=exact, value="{current_year}-01-15"
    """
    type: Literal["exact", "relative", "current_period"]
    unit:   Optional[Literal["day", "month", "year", "quarter"]] = None
    amount: Optional[int] = None    # Geçmiş: negatif, gelecek: pozitif
    period: Optional[Literal["day", "month", "year", "quarter"]] = None
    value:  Optional[str] = None    # "YYYY-MM-DD" formatı (exact için)


class SchemaFilter(BaseModel):
    """Tek bir WHERE koşulu."""
    column:           str       # Gerçek DB kolon adı (column_metadata'dan)
    operator:         Literal[
        "=", ">", "<", ">=", "<=", "!=",
        "LIKE", "IS NULL", "IS NOT NULL", "BETWEEN"
    ]
    value:            Optional[str] = None           # String/sayı değer
    date_descriptor:  Optional[DateDescriptor] = None  # Tarih filtresi ise bunu doldur
    value_hint:       Optional[str] = None           # Orijinal kullanıcı değeri (fuzzy için)
    logical_operator: Literal["AND", "OR"] = "AND"
    # value_resolver tarafından doldurulur:
    resolved_value:        Optional[str] = None
    resolution_confidence: Optional[float] = None


class SchemaAggregation(BaseModel):
    """Tek bir aggregation ifadesi."""
    function: Literal["SUM", "COUNT", "AVG", "MAX", "MIN"]
    column:   str    # Gerçek DB kolon adı
    alias:    str    # Sonuç kolon alias'ı (ör: "ToplamCiro")


class QuerySchema(BaseModel):
    """
    sql_architect node'unun structured output'u.
    Tüm alanlar gerçek DB kolon adları içerir — Python bu şemadan SQL üretir.
    """
    description:        str
    select_columns:     List[str]            # Aggregation yoksa gösterilecek kolonlar (boş olabilir)
    filters:            List[SchemaFilter]
    aggregations:       List[SchemaAggregation]
    group_by:           List[str]            # Gerçek kolon adları veya SQL expression
    order_by_column:    Optional[str] = None
    order_by_direction: Literal["ASC", "DESC"] = "DESC"
    limit:              Optional[int] = None
    applied_rule_ids:   List[str] = []       # Business rule ID'leri — Python SQL'e ekler


# =============================================================================
# PROMPT
# =============================================================================

SQL_ARCHITECT_PROMPT = """Sen bir T-SQL sorgu mimarısın. Kullanıcı sorusunu analiz et ve yapılandırılmış bir sorgu şeması (QuerySchema) üret.

## BUGÜNÜN TARİHİ
- Tarih: {today_date}
- Yıl: {current_year}
- Ay: {current_month}
- Çeyrek: {current_quarter}

## KULLANICI SORUSU
{user_query}

## SORGU TİPİ
{query_type}

## VERİTABANI KOLON BİLGİLERİ
{column_metadata}

## UYGULANACAK İŞ KURALLARI (ChromaDB'den seçilmiş)
{business_rules_context}

## KONUŞMA BAĞLAMI
{conversation_context}

## ÖNCEKİ SQL HATASI (varsa — şemayı buna göre düzelt)
{sql_error}

---

## KURALLAR

### KURAL 1 — Kolon Adları
SADECE yukarıdaki KOLON BİLGİLERİ'ndeki gerçek DB adlarını kullan.
Kullanıcı "şube" derse → kolon açıklamalarına bak, doğru DB kolon adını yaz.
Hiçbir zaman "tarih", "şube", "tutar" gibi Türkçe field_hint yazma — gerçek DB adını yaz.

### KURAL 2 — Tarih Filtreleri (DateDescriptor ZORUNLU)
Tarih olan filtreler için value/value_hint DEĞİL, date_descriptor doldur.

Örnekler:
  "son 3 ay"      → {{"type":"relative","unit":"month","amount":-3}},   operator: ">="
  "son 7 gün"     → {{"type":"relative","unit":"day","amount":-7}},     operator: ">="
  "son 1 yıl"     → {{"type":"relative","unit":"year","amount":-1}},    operator: ">="
  "bu yıl"        → {{"type":"current_period","period":"year"}}
  "bu ay"         → {{"type":"current_period","period":"month"}}
  "bugün"         → {{"type":"current_period","period":"day"}}
  "bu çeyrek"     → {{"type":"current_period","period":"quarter"}}
  "15 ocak"       → {{"type":"exact","value":"{current_year}-01-15"}},  operator: "="
  "ocak 2024"     → iki filter: >= {{"type":"exact","value":"2024-01-01"}}
                              ve <= {{"type":"exact","value":"2024-01-31"}}

Tarih filtresi için value alanını KULLANMA — date_descriptor kullan.

### KURAL 3 — GROUP BY Zorunluluğu (KRİTİK)
Aggregation varsa:
  - select_columns: BOŞ bırak []
  - group_by: tüm non-aggregate kolonları ekle
  - aggregations: SUM/COUNT/AVG/MAX/MIN ile doldur

YANLIŞ ❌:
  select_columns=["ProductName"], aggregations=[SUM(Quantity)], group_by=[]

DOĞRU ✅:
  select_columns=[], aggregations=[SUM(Quantity) AS TotalQty], group_by=["ProductName"]

### KURAL 4 — RANKING Sorguları
"Top 10 / en çok / en az / sıralama" → limit + order_by_column + en az 1 aggregation ZORUNLU.
Örnek: "en çok satan 10 ürün" → aggregations=[SUM(Quantity)], group_by=["ProductName"],
       order_by_column="TotalQty", order_by_direction="DESC", limit=10

### KURAL 5 — Periyodik Gruplama
"günlük satışlar"  → group_by: ["CAST(TarihKolonu AS DATE)"]
"aylık satışlar"   → group_by: ["YEAR(TarihKolonu)", "MONTH(TarihKolonu)"]
"yıllık satışlar"  → group_by: ["YEAR(TarihKolonu)"]
"saatlik dağılım"  → group_by: ["CAST(TarihKolonu AS DATE)", "HourKolonu"]
Tarih kolonu adını column_metadata'dan al.

### KURAL 6 — Business Rules
KURALLAR bölümündeki her kural için ID listesini applied_rule_ids'e yaz.
SQL bileşenlerini (WHERE koşulu, SUM ifadesi) KENDİN YAZMA — Python uygular.
Sadece hangi rule'un uygulanacağını belirt.

### KURAL 7 — Hata Düzeltme
ÖNCEKİ SQL HATASI varsa:
  - Hata mesajını analiz et
  - Yanlış kolon adı → column_metadata'dan doğrusunu bul
  - GROUP BY hatası → Kural 3'ü uygula
  - Syntax hatası → ilgili field'ı düzelt
"""
```

**Step 2: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "feat(text2sql): replace prompt models with QuerySchema + SQL_ARCHITECT_PROMPT"
```

---

## Task 3: sql_builder.py — Pure Python SQL Generator (YENİ DOSYA)

**File:** `src/graphs/report_agent/subagents/text2sql/sql_builder.py`

**Step 1: Dosyayı oluştur**

```python
"""
Pure Python T-SQL Generator
============================
QuerySchema + business_rules + today → T-SQL string.
LLM kullanmaz. Deterministik ve test edilebilir.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def _col_expr(col: str) -> str:
    """Basit kolon adını [köşeli parantez] içine al; SQL expression ise olduğu gibi bırak."""
    if any(c in col for c in ("(", ")", " ", ".")):
        return col  # YEAR(DocumentDate), CAST(...) gibi — dokunma
    return f"[{col}]"


def _resolve_date_filter(col_expr: str, descriptor: Dict[str, Any], operator: str, today: date) -> str:
    """DateDescriptor dict'ini SQL koşuluna çevir."""
    d_type = descriptor.get("type")

    if d_type == "exact":
        val = descriptor.get("value", "")
        return f"{col_expr} {operator} '{val}'"

    elif d_type == "relative":
        unit_map = {"day": "DAY", "month": "MONTH", "year": "YEAR", "quarter": "QUARTER"}
        sql_unit = unit_map.get(descriptor.get("unit", "day"), "DAY")
        amount = descriptor.get("amount", -1)
        date_expr = f"DATEADD({sql_unit}, {amount}, '{today}')"
        # relative için "=" anlamsız — ">=" kullan
        effective_op = operator if operator not in ("=",) else ">="
        return f"{col_expr} {effective_op} {date_expr}"

    elif d_type == "current_period":
        period = descriptor.get("period", "day")
        if period == "day":
            return f"CAST({col_expr} AS DATE) = '{today}'"
        elif period == "month":
            return f"YEAR({col_expr}) = {today.year} AND MONTH({col_expr}) = {today.month}"
        elif period == "year":
            return f"YEAR({col_expr}) = {today.year}"
        elif period == "quarter":
            q = (today.month - 1) // 3 + 1
            return f"YEAR({col_expr}) = {today.year} AND DATEPART(QUARTER, {col_expr}) = {q}"

    return ""


def _resolve_filter(f: Dict[str, Any], today: date) -> Optional[str]:
    """Tek SchemaFilter dict'ini SQL koşul string'ine çevir. None = atla."""
    col = _col_expr(f["column"])
    op = f.get("operator", "=")

    # IS NULL / IS NOT NULL — değer gerektirmez
    if op in ("IS NULL", "IS NOT NULL"):
        return f"{col} {op}"

    # Tarih filtresi
    date_desc = f.get("date_descriptor")
    if date_desc:
        result = _resolve_date_filter(col, date_desc, op, today)
        if result:
            return result

    # Normal değer filtresi
    value = f.get("resolved_value") or f.get("value")

    if not value:
        # value_hint varsa LIKE fallback
        hint = f.get("value_hint", "")
        if hint:
            clean = hint.replace("'", "''")
            return f"UPPER({col}) LIKE UPPER('%{clean}%')"
        return None  # Atla

    value_clean = value.replace("'", "''")

    if op == "LIKE":
        return f"UPPER({col}) LIKE UPPER('%{value_clean}%')"
    elif op == "BETWEEN":
        # value "val1 AND val2" formatında olmalı
        return f"{col} BETWEEN {value}"
    else:
        # Sayısal mı?
        try:
            float(value_clean.replace(",", "."))
            return f"{col} {op} {value_clean}"
        except ValueError:
            return f"{col} {op} '{value_clean}'"


def _build_select_parts(schema_dict: Dict[str, Any], applied_rules: List[Dict[str, Any]]) -> List[str]:
    """SELECT cümlesi için parça listesi oluştur."""
    aggregations = schema_dict.get("aggregations", [])
    select_columns = schema_dict.get("select_columns", [])
    group_by = schema_dict.get("group_by", [])

    if aggregations:
        parts: List[str] = []

        # GROUP BY kolonlarını önce ekle (display için)
        for col in group_by:
            parts.append(_col_expr(col))

        # Aggregation ifadelerini ekle
        agg_rule_modifier = next(
            (r["sql"].get("aggregation", "") for r in applied_rules if r.get("sql", {}).get("aggregation")),
            None,
        )

        for agg in aggregations:
            func = agg["function"]
            col_expr = _col_expr(agg["column"])
            alias = agg["alias"]

            if agg_rule_modifier and func == "SUM":
                # Business rule aggregation içeriğini kullan
                inner = agg_rule_modifier.replace("{col}", agg["column"]).replace("{column}", agg["column"])
                parts.append(f"{func}({inner}) AS [{alias}]")
            else:
                parts.append(f"{func}({col_expr}) AS [{alias}]")

        return parts

    elif select_columns:
        return [_col_expr(col) for col in select_columns]
    else:
        return ["*"]


def _build_where(
    filters: List[Dict[str, Any]],
    applied_rules: List[Dict[str, Any]],
    today: date,
) -> str:
    """WHERE cümlesi oluştur. Boş string döner = WHERE yok."""
    conditions: List[tuple[str, str]] = []  # (logical_op, condition)

    for f in filters:
        condition = _resolve_filter(f, today)
        if condition:
            conditions.append((f.get("logical_operator", "AND"), condition))

    # Business rule WHERE bileşenleri
    for rule in applied_rules:
        sql_filter = rule.get("sql", {}).get("filter", "")
        if sql_filter:
            conditions.append(("AND", sql_filter))

    if not conditions:
        return ""

    parts = [conditions[0][1]]
    for logical_op, condition in conditions[1:]:
        parts.append(f"{logical_op} {condition}")

    return "WHERE " + "\n    ".join(parts)


def _build_group_by(schema_dict: Dict[str, Any], applied_rules: List[Dict[str, Any]]) -> str:
    """GROUP BY cümlesi oluştur."""
    group_by = schema_dict.get("group_by", [])
    if not group_by:
        return ""

    cols = [_col_expr(col) for col in group_by]

    # Business rule group_by eklemesi
    for rule in applied_rules:
        extra = rule.get("sql", {}).get("group_by", "")
        if extra:
            cols.append(extra)

    return "GROUP BY " + ", ".join(cols)


def _build_order_by(schema_dict: Dict[str, Any]) -> str:
    """ORDER BY cümlesi oluştur."""
    order_col = schema_dict.get("order_by_column")
    direction = schema_dict.get("order_by_direction", "DESC")

    if order_col:
        return f"ORDER BY {_col_expr(order_col)} {direction}"

    # Periyodik gruplama varsa otomatik ORDER BY
    group_by = schema_dict.get("group_by", [])
    time_indicators = ("YEAR(", "MONTH(", "CAST(", "DATEPART(")
    time_cols = [col for col in group_by if any(col.upper().startswith(t) for t in time_indicators)]
    if time_cols:
        return "ORDER BY " + ", ".join(time_cols) + " ASC"

    # RANKING: aggregation + limit varsa birinci aggregation'a göre sırala
    aggregations = schema_dict.get("aggregations", [])
    if aggregations and schema_dict.get("limit"):
        alias = aggregations[0].get("alias", "")
        if alias:
            return f"ORDER BY [{alias}] {direction}"

    return ""


# =============================================================================
# PUBLIC API
# =============================================================================

def generate_sql(
    schema_dict: Dict[str, Any],
    table_name: str,
    full_rules_data: List[Dict[str, Any]],
    today: date,
) -> str:
    """
    QuerySchema dict + business rules + bugünün tarihi → T-SQL string.

    Args:
        schema_dict: QuerySchema.model_dump() çıktısı
        table_name:  Hedef tablo adı (runtime config'ten gelir)
        full_rules_data: business_rules.json'dan yüklenen tam kural listesi
        today:       Bugünün tarihi (tarih çözme için)

    Returns:
        Executable T-SQL string
    """
    # Uygulanan rule'ların tam verisini çek
    applied_ids: List[str] = schema_dict.get("applied_rule_ids", [])
    applied_rules = [r for r in full_rules_data if r.get("id") in applied_ids]

    if applied_rules:
        logger.info(f"[SQL_GENERATOR] Applying {len(applied_rules)} business rules: {applied_ids}")

    # TOP N
    limit = schema_dict.get("limit")
    top_clause = f"TOP {limit} " if limit else ""

    # SELECT
    select_parts = _build_select_parts(schema_dict, applied_rules)
    select_clause = ",\n       ".join(select_parts)

    # FROM
    from_clause = f"[{table_name}]"

    # WHERE
    where_clause = _build_where(schema_dict.get("filters", []), applied_rules, today)

    # GROUP BY
    group_by_clause = _build_group_by(schema_dict, applied_rules)

    # ORDER BY
    order_by_clause = _build_order_by(schema_dict)

    # Birleştir
    lines = [f"SELECT {top_clause}{select_clause}", f"FROM {from_clause}"]
    if where_clause:
        lines.append(where_clause)
    if group_by_clause:
        lines.append(group_by_clause)
    if order_by_clause:
        lines.append(order_by_clause)

    sql = "\n".join(lines)
    logger.info(f"[SQL_GENERATOR] Generated ({len(sql)} chars): {sql[:200]}")
    return sql
```

**Step 2: Hızlı smoke test — Python'dan çalıştır**

```python
# Bir terminal veya notebook'ta test et:
from datetime import date
from src.graphs.report_agent.subagents.text2sql.sql_builder import generate_sql

schema = {
    "description": "Test",
    "select_columns": [],
    "filters": [{"column": "BranchName", "operator": "=", "value": None,
                 "value_hint": "tunalı", "resolved_value": "TUNALI ŞUBESİ",
                 "logical_operator": "AND"}],
    "aggregations": [{"function": "SUM", "column": "RowAmount", "alias": "ToplamCiro"}],
    "group_by": ["ProductName"],
    "order_by_column": "ToplamCiro",
    "order_by_direction": "DESC",
    "limit": 10,
    "applied_rule_ids": [],
}
sql = generate_sql(schema, "MasterReportDocumentTable", [], date.today())
print(sql)
# Beklenen çıktı:
# SELECT TOP 10 [ProductName],
#        SUM([RowAmount]) AS [ToplamCiro]
# FROM [MasterReportDocumentTable]
# WHERE [BranchName] = 'TUNALI ŞUBESİ'
# GROUP BY [ProductName]
# ORDER BY [ToplamCiro] DESC
```

**Step 3: Tarih filtresini test et**

```python
schema_date = {
    "description": "Tarih testi",
    "select_columns": ["ProductName", "RowAmount"],
    "filters": [{
        "column": "DocumentDate",
        "operator": ">=",
        "date_descriptor": {"type": "relative", "unit": "month", "amount": -3},
        "logical_operator": "AND"
    }],
    "aggregations": [],
    "group_by": [],
    "order_by_column": None,
    "order_by_direction": "DESC",
    "limit": None,
    "applied_rule_ids": [],
}
sql2 = generate_sql(schema_date, "MasterReportDocumentTable", [], date(2025, 2, 23))
print(sql2)
# Beklenen:
# SELECT [ProductName],
#        [RowAmount]
# FROM [MasterReportDocumentTable]
# WHERE [DocumentDate] >= DATEADD(MONTH, -3, '2025-02-23')
```

**Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/sql_builder.py
git commit -m "feat(text2sql): add pure Python SQL generator (sql_builder.py)"
```

---

## Task 4: nodes.py — Yeni node'lar

**File:** `src/graphs/report_agent/subagents/text2sql/nodes.py`

Değişiklikler:
- `create_sql_planner_node` → `create_sql_architect_node` (1 LLM çağrısı, tarih inject)
- `create_sql_builder_node` → `create_sql_generator_node` (Pure Python)
- `create_value_resolver_node` → `query_schema.filters` oku, interrupt() ekle
- `create_business_rules_node` → rule ID'lerini içerecek format

**Step 1: Import bölümünü güncelle (dosyanın başı)**

Mevcut import'ları şöyle değiştir:

```python
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
```

**Step 2: `_get_configurable`, `_db_executor`, `MAX_RETRY` sabitlerini koru (değişmez)**

**Step 3: `create_business_rules_node` güncelle — rule ID içerecek format döndür**

Mevcut fonksiyonu bul ve şöyle değiştir:

```python
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

        merged = result.get("merged_sql", {})
        if not merged:
            logger.info("[BUSINESS_RULES] No relevant rules found")
            return {"business_rules_context": "Uygulanacak kural bulunamadı."}

        # Yeni format: ID + açıklama + SQL bileşenleri (LLM ID'leri okuyabilsin)
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
```

**Step 4: `create_sql_architect_node` ekle (sql_planner'ın yerine)**

Mevcut `create_sql_planner_node` fonksiyonunu tamamen şununla değiştir:

```python
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
```

**Step 5: `create_value_resolver_node` güncelle — query_schema okusun + interrupt()**

Mevcut `create_value_resolver_node` fonksiyonunu şununla değiştir:

```python
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
```

**Step 6: `create_sql_generator_node` ekle (sql_builder_node'un yerine)**

Mevcut `create_sql_builder_node` fonksiyonunu şununla değiştir:

```python
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
```

**Step 7: `create_sql_executor_node` güncelle — retry state'i temizle**

Mevcut executor'da küçük değişiklik: başarı durumunda `query_schema` state'te kalabilir — bu sorun değil. Ama `sql_error` ve `retry_count` temizlenmeli. Mevcut kod bunu zaten yapıyor, dokunma.

**Step 8: Eski fonksiyonları sil**

`create_sql_planner_node` ve `create_sql_builder_node` isimli fonksiyonlar artık yok — tamamen kaldır.

**Step 9: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat(text2sql): add sql_architect + sql_generator nodes, update value_resolver"
```

---

## Task 5: graph.py — Node sırası ve routing güncelleme

**File:** `src/graphs/report_agent/subagents/text2sql/graph.py`

Değişiklikler:
- Import: `create_sql_architect_node`, `create_sql_generator_node` ekle; eski isimleri kaldır
- `full_rules_data` JSON'dan yükle, `create_sql_generator_node`'a geç
- Node sırası: `create_table → business_rules → sql_architect → value_resolver → sql_generator → sql_executor → cleanup_table`
- Retry routing: `sql_executor → sql_architect` (eski: sql_builder)

**Step 1: Dosyayı tamamen yeniden yaz**

```python
"""
Text2SQL Subagent Graph (v2)

START → create_table → business_rules → sql_architect → value_resolver
        → sql_generator → sql_executor ──────────────────────────────────┐
                               ↑ (retry, max 2)                           │
                               └──────────────────────────────────────────┘
                                                                           ↓
                                                                    cleanup_table → END

create_table / cleanup_table: runtime config'te query varsa çalışır, yoksa no-op.
sql_architect: TEK LLM çağrısı. Retry'da sql_error bağlamıyla yeniden çağrılır.
sql_generator: Pure Python. LLM yok.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.subagents.text2sql.business_rules_vector_store import BusinessRulesVectorStore
from src.graphs.report_agent.subagents.text2sql.nodes import (
    MAX_RETRY,
    create_business_rules_node,
    create_cleanup_table_node,
    create_create_table_node,
    create_sql_architect_node,
    create_sql_executor_node,
    create_sql_generator_node,
    create_value_resolver_node,
)
from src.graphs.report_agent.subagents.text2sql.state import Text2SQLState
from src.graphs.report_agent.subagents.text2sql.value_resolver_service import ValueResolverService

logger = logging.getLogger(__name__)


def _route_after_executor(state: dict) -> str:
    """
    Retry routing:
      sql_error set ve retry < MAX_RETRY → sql_architect (LLM yeniden şema üretir)
      Aksi halde → cleanup_table
    """
    if state.get("sql_error") and state.get("retry_count", 0) <= MAX_RETRY:
        logger.info(f"[TEXT2SQL] Retry {state['retry_count']}/{MAX_RETRY} → sql_architect")
        return "sql_architect"
    return "cleanup_table"


def build_text2sql_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    connection_string: str,
    business_rules_path: str,
    chroma_persist_dir: str,
):
    """
    Text2SQL subgraph'ı inşa et.

    Args:
        llm:                 ChatOpenAI veya uyumlu LLM
        table_name:          Default tablo adı (runtime config override edebilir)
        column_metadata:     {kolon_adı: açıklama} — runtime config override edebilir
        connection_string:   pyodbc / mssql+pyodbc bağlantı string'i
        business_rules_path: business_rules.json dosya yolu
        chroma_persist_dir:  ChromaDB persist klasörü
    """
    logger.info(f"[TEXT2SQL] Building subgraph v2 for table: {table_name}")

    # --- Servis başlatma ---
    value_resolver = ValueResolverService(
        db_connection_string=connection_string,
        table_name=table_name,
    )

    vector_store = BusinessRulesVectorStore(
        rules_file_path=business_rules_path,
        persist_directory=chroma_persist_dir,
    )
    vector_store.initialize_collections()

    # --- Full rules data (sql_generator için) ---
    try:
        with open(business_rules_path, "r", encoding="utf-8") as f:
            rules_json = json.load(f)
        full_rules_data = rules_json if isinstance(rules_json, list) else rules_json.get("rules", [])
        logger.info(f"[TEXT2SQL] Loaded {len(full_rules_data)} business rules for sql_generator")
    except Exception as e:
        logger.warning(f"[TEXT2SQL] Could not load business rules JSON: {e}")
        full_rules_data = []

    # --- Node factories ---
    create_table   = create_create_table_node(connection_string, table_name)
    business_rules = create_business_rules_node(vector_store)
    sql_architect  = create_sql_architect_node(llm, column_metadata)
    value_resolver_node = create_value_resolver_node(value_resolver)
    sql_generator  = create_sql_generator_node(table_name, full_rules_data)
    sql_executor   = create_sql_executor_node(connection_string)
    cleanup_table  = create_cleanup_table_node(connection_string, table_name)

    # --- Graph ---
    graph = StateGraph(Text2SQLState)

    graph.add_node("create_table",   create_table)
    graph.add_node("business_rules", business_rules)
    graph.add_node("sql_architect",  sql_architect)
    graph.add_node("value_resolver", value_resolver_node)
    graph.add_node("sql_generator",  sql_generator)
    graph.add_node("sql_executor",   sql_executor)
    graph.add_node("cleanup_table",  cleanup_table)

    graph.add_edge(START,            "create_table")
    graph.add_edge("create_table",   "business_rules")
    graph.add_edge("business_rules", "sql_architect")
    graph.add_edge("sql_architect",  "value_resolver")
    graph.add_edge("value_resolver", "sql_generator")
    graph.add_edge("sql_generator",  "sql_executor")
    graph.add_conditional_edges(
        "sql_executor",
        _route_after_executor,
        {"sql_architect": "sql_architect", "cleanup_table": "cleanup_table"},
    )
    graph.add_edge("cleanup_table",  END)

    compiled = graph.compile()
    logger.info(
        "[TEXT2SQL] Subgraph v2 built: "
        "create_table → business_rules → sql_architect → value_resolver "
        "→ sql_generator → sql_executor → cleanup_table (max 2 retry)"
    )
    return compiled
```

**Step 2: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/graph.py
git commit -m "feat(text2sql): rewrite graph v2 - single LLM call, Python SQL generator"
```

---

## Task 6: Son kontrol

**Step 1: LangGraph Studio'da başlat**

```bash
langgraph dev
```

**Step 2: report_agent graph'ını seç**

Studio'da `report_agent` graph'ını aç.

**Step 3: Configurable panelinden ayarla**

```json
{
  "table_name": "MasterReportDocumentTable",
  "column_metadata": {"DocumentDate": "Satış tarihi", "BranchName": "Şube adı", ...},
  "query": ""
}
```

**Step 4: Test mesajları gönder**

```
1. "Toplam ciro ne kadar?"                   → basit SUM
2. "Son 3 aydaki şube bazında satışlar"       → tarih + group_by
3. "En çok satan 10 ürün"                    → RANKING (limit + ORDER BY)
4. "Tunalı şubesinin aylık satışları"         → branch filter + aylık gruplama
```

**Step 5: graph.py import hatası varsa kontrol et**

`create_sql_planner_node` veya `create_sql_builder_node` referansı kalmışsa temizle.

**Step 6: Final commit**

```bash
git add -p  # Varsa kalan değişiklikler
git commit -m "fix(text2sql): cleanup stale references after v2 rewrite"
```
