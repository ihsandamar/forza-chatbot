# Date Resolver Tool Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `sql_architect` node içinde LLM tool-calling loop ekle: LLM sorgudaki tarih ifadelerini tespit edip `resolve_date` tool'unu çağırır, tool Python ile SQL expression üretir; ardından aynı node içinde QuerySchema üretilir. Ayrı node yok.

**Architecture:** `sql_architect_node` iki aşamalı çalışır:
1. `llm.bind_tools([resolve_date])` → LLM tarih ifadelerini yakalar, tool çağırır → SQL expression'lar döner
2. `llm.with_structured_output(QuerySchema)` → Resolved date'ler prompt'a inject edilmiş halde QuerySchema üretir

**Tech Stack:** Python 3.12, LangChain `@tool`, `bind_tools`, `ToolMessage`, `HumanMessage`, datetime (stdlib)

**Design Kararları:**
- `resolve_date` tool tamamen Python/deterministik — LLM sadece **hangi ifadeyi** çözeceğini söyler
- Tool calling loop max 5 iterasyon (sonsuz döngü koruması)
- Tool call yoksa (tarih ifadesi yok) → direkt structured output'a geç
- `date_tool.py` standalone — test edilebilir
- LLM tool call yaparken aynı zamanda structured output üretemez → iki ayrı API çağrısı ama tek LangGraph node

---

## Referans Dosyalar

Yeni:
- `src/graphs/report_agent/subagents/text2sql/date_tool.py`

Değiştirilecek:
- `src/graphs/report_agent/subagents/text2sql/nodes.py` (`create_sql_architect_node`)
- `src/graphs/report_agent/subagents/text2sql/prompts.py` (`SQL_ARCHITECT_PROMPT` + tool talimatı)

---

## Task 1: date_tool.py — `@tool resolve_date` oluştur

**File:** `src/graphs/report_agent/subagents/text2sql/date_tool.py`

**Step 1: Dosyayı oluştur**

```python
"""
Date Tool
=========
LLM'in çağırdığı tool: Türkçe tarih ifadesi → T-SQL date expression.
LangChain @tool decorator ile tanımlanır.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Literal, Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Türkçe normalizer (tool içinde kullanılır)
def _n(text: str) -> str:
    return (
        text.lower()
        .replace("ı", "i").replace("İ", "i")
        .replace("ğ", "g").replace("Ğ", "g")
        .replace("ü", "u").replace("Ü", "u")
        .replace("ş", "s").replace("Ş", "s")
        .replace("ö", "o").replace("Ö", "o")
        .replace("ç", "c").replace("Ç", "c")
    )

_UNIT_MAP = {
    "gun": "DAY", "gün": "DAY",
    "hafta": "WEEK",
    "ay": "MONTH",
    "yil": "YEAR", "yıl": "YEAR", "sene": "YEAR",
}

_MONTH_MAP = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4,
    "mayis": 5, "haziran": 6, "temmuz": 7, "agustos": 8,
    "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
}


@tool
def resolve_date(expression: str) -> str:
    """
    Türkçe tarih ifadesini T-SQL date expression'a çevirir.

    Kullanım: Sorguda geçen her tarih ifadesi için bu tool'u çağır.
    Desteklenen ifadeler:
      - "son N gün/hafta/ay/yıl"  → DATEADD(...)
      - "N yıl/ay önce"           → DATEADD(...)
      - "geçen yıl / geçen ay"    → YEAR(col) = ...
      - "bu yıl / bu ay / bugün / bu çeyrek / bu hafta"
      - "ocak 2024" / "2024 ocak" → tarih aralığı
      - "2024-01-15"              → CAST(col AS DATE) = '2024-01-15'

    Returns:
        SQL fragment string.
        '{col}' placeholder'ı gerçek tarih kolonu adıyla değiştirilecektir.
        Operator bilgisi "OP:" prefix'iyle döner (ör: "OP:>= DATEADD(...)").
    """
    today = date.today()
    q = _n(expression.strip())

    # --- son N gün/hafta/ay/yıl ---
    m = re.search(r"son\s+(\d+)\s*(gun|hafta|ay|yil|sene)", q)
    if m:
        n, unit_key = int(m.group(1)), m.group(2)
        sql_unit = _UNIT_MAP.get(unit_key, "DAY")
        result = f"OP:>= DATEADD({sql_unit}, -{n}, '{today}')"
        logger.info(f"[DATE_TOOL] '{expression}' → {result}")
        return result

    # --- N yıl/ay/gün önce ---
    m = re.search(r"(\d+)\s*(gun|hafta|ay|yil|sene)\s+once", q)
    if m:
        n, unit_key = int(m.group(1)), m.group(2)
        sql_unit = _UNIT_MAP.get(unit_key, "DAY")
        result = f"OP:>= DATEADD({sql_unit}, -{n}, '{today}')"
        logger.info(f"[DATE_TOOL] '{expression}' → {result}")
        return result

    # --- geçen yıl ---
    if re.search(r"gecen\s*yil", q):
        result = f"YEAR({{col}}) = {today.year - 1}"
        logger.info(f"[DATE_TOOL] 'geçen yıl' → {result}")
        return result

    # --- geçen ay ---
    if re.search(r"gecen\s*ay", q):
        prev = (today.replace(day=1) - timedelta(days=1))
        result = f"YEAR({{col}}) = {prev.year} AND MONTH({{col}}) = {prev.month}"
        logger.info(f"[DATE_TOOL] 'geçen ay' → {result}")
        return result

    # --- bu yıl ---
    if re.search(r"bu\s*yil", q):
        result = f"YEAR({{col}}) = {today.year}"
        logger.info(f"[DATE_TOOL] 'bu yıl' → {result}")
        return result

    # --- bu ay ---
    if re.search(r"bu\s*ay", q):
        result = f"YEAR({{col}}) = {today.year} AND MONTH({{col}}) = {today.month}"
        logger.info(f"[DATE_TOOL] 'bu ay' → {result}")
        return result

    # --- bugün ---
    if re.search(r"bugun", q):
        result = f"CAST({{col}} AS DATE) = '{today}'"
        logger.info(f"[DATE_TOOL] 'bugün' → {result}")
        return result

    # --- bu çeyrek ---
    if re.search(r"bu\s*(ceyrek|cayrak)", q):
        q_num = (today.month - 1) // 3 + 1
        result = f"YEAR({{col}}) = {today.year} AND DATEPART(QUARTER, {{col}}) = {q_num}"
        logger.info(f"[DATE_TOOL] 'bu çeyrek' → {result}")
        return result

    # --- bu hafta ---
    if re.search(r"bu\s*hafta", q):
        monday = today - timedelta(days=today.weekday())
        result = f"CAST({{col}} AS DATE) >= '{monday}' AND CAST({{col}} AS DATE) <= '{today}'"
        logger.info(f"[DATE_TOOL] 'bu hafta' → {result}")
        return result

    # --- ocak 2024 / 2024 ocak ---
    for month_tr, month_no in _MONTH_MAP.items():
        m5 = re.search(rf"{month_tr}\s+(\d{{4}})", q) or re.search(rf"(\d{{4}})\s+{month_tr}", q)
        if m5:
            year = int(m5.group(1))
            # Son günü hesapla
            if month_no == 12:
                last_day = 31
            else:
                last_day = (date(year, month_no + 1, 1) - timedelta(days=1)).day
            result = (
                f"OP:BETWEEN '{year}-{month_no:02d}-01' "
                f"AND '{year}-{month_no:02d}-{last_day:02d}'"
            )
            logger.info(f"[DATE_TOOL] '{expression}' (ay-yıl) → {result}")
            return result

    # --- ISO tarih 2024-01-15 ---
    m6 = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", expression)
    if m6:
        iso = m6.group(1)
        result = f"OP:= '{iso}'"
        logger.info(f"[DATE_TOOL] ISO date '{iso}' → {result}")
        return result

    # Çözülemedi
    logger.warning(f"[DATE_TOOL] Could not resolve: '{expression}'")
    return f"UNRESOLVED: {expression}"
```

**Step 2: Unit test yaz**

Dosya: `tests/graphs/report_agent/text2sql/test_date_tool.py`

```python
from unittest.mock import patch
from datetime import date
import pytest

# date.today()'u sabitle
FIXED_TODAY = date(2026, 2, 24)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    class FakeDate(date):
        @classmethod
        def today(cls):
            return FIXED_TODAY
    monkeypatch.setattr(
        "src.graphs.report_agent.subagents.text2sql.date_tool.date",
        FakeDate,
    )


from src.graphs.report_agent.subagents.text2sql.date_tool import resolve_date


def test_son_n_yil():
    result = resolve_date.invoke({"expression": "son 1 yılda"})
    assert "OP:>=" in result
    assert "DATEADD(YEAR, -1, '2026-02-24')" in result


def test_son_n_ay():
    result = resolve_date.invoke({"expression": "son 3 ay"})
    assert "DATEADD(MONTH, -3" in result


def test_bu_yil():
    result = resolve_date.invoke({"expression": "bu yıl"})
    assert "2026" in result
    assert "YEAR" in result


def test_gecen_yil():
    result = resolve_date.invoke({"expression": "geçen yıl"})
    assert "2025" in result


def test_ay_yil():
    result = resolve_date.invoke({"expression": "ocak 2024"})
    assert "2024-01-01" in result
    assert "2024-01-31" in result


def test_iso_date():
    result = resolve_date.invoke({"expression": "2024-03-15"})
    assert "2024-03-15" in result


def test_unresolvable():
    result = resolve_date.invoke({"expression": "bilinmeyen ifade"})
    assert "UNRESOLVED" in result
```

**Step 3: Test çalıştır**

```bash
pytest tests/graphs/report_agent/text2sql/test_date_tool.py -v
```

Beklenen: Tüm testler PASS

**Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/date_tool.py \
        tests/graphs/report_agent/text2sql/test_date_tool.py
git commit -m "feat(text2sql): add resolve_date @tool - deterministic Turkish date → T-SQL"
```

---

## Task 2: prompts.py — Tool talimatını SQL_ARCHITECT_PROMPT'a ekle

**File:** `src/graphs/report_agent/subagents/text2sql/prompts.py`

**Step 1: KURAL 2'yi güncelle**

Mevcut KURAL 2 (DateDescriptor ile doldur) yerine:

```
### KURAL 2 — Tarih Filtreleri (resolve_date TOOL ZORUNLU)
Sorguda tarih ifadesi varsa ("son 3 ay", "bu yıl", "ocak 2024" gibi):
  1. resolve_date("ifade") tool'unu çağır
  2. Tool "{col}" placeholder'lı SQL döner — {col} yerine column_metadata'dan doğru tarih kolonu adını yaz
  3. OP:>= ile başlıyorsa → operator: ">=", value: DATEADD(...) kısmı
     OP:BETWEEN ile başlıyorsa → operator: "BETWEEN", value: tarih aralığı
     OP:= ile başlıyorsa → operator: "=", value: tarih
     Düz expression ise (YEAR(...)) → value alanına direkt yaz, date_descriptor kullanma

Tarih filtresinde date_descriptor KULLANMA — tool sonucunu kullan.
```

**Step 2: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "feat(text2sql): update KURAL 2 - instruct LLM to use resolve_date tool"
```

---

## Task 3: nodes.py — `create_sql_architect_node` tool-calling loop ekle

**File:** `src/graphs/report_agent/subagents/text2sql/nodes.py`

**Step 1: Import ekle**

```python
from langchain_core.messages import HumanMessage, ToolMessage

from src.graphs.report_agent.subagents.text2sql.date_tool import resolve_date
```

**Step 2: `create_sql_architect_node` içini güncelle**

```python
def create_sql_architect_node(llm, column_metadata: Dict[str, Any]) -> Callable:
    """
    LLM (TOOL-CALLING + STRUCTURED OUTPUT): user_query → QuerySchema.

    İki aşama, tek LangGraph node:
      1. Tool-calling loop: LLM resolve_date tool'unu çağırarak tarih ifadelerini çözer
      2. Structured output: Resolved context ile QuerySchema üretir
    """
    llm_with_tools   = llm.bind_tools([resolve_date])
    structured_llm   = llm.with_structured_output(QuerySchema)
    MAX_TOOL_ROUNDS  = 5

    async def sql_architect_node(state: dict, *, config: RunnableConfig = None) -> dict:
        user_query              = state.get("user_query", "")
        query_type              = state.get("query_type", "SINGLE")
        business_rules_context  = state.get("business_rules_context") or "Uygulanacak kural bulunamadı."
        active_sql              = state.get("active_sql")
        active_filters          = state.get("active_filters") or []
        sql_error               = state.get("sql_error") or "Yok"
        effective_metadata      = _get_configurable(config, "column_metadata", column_metadata)
        today                   = date.today()

        conversation_context = "Yeni sorgu, önceki bağlam yok."
        if active_sql:
            conversation_context = f"Önceki SQL: {active_sql[:300]}"
            if active_filters:
                conversation_context += f"\nAktif filtreler: {json.dumps(active_filters[:3], ensure_ascii=False)}"

        # --- Aşama 1: Tool-calling loop (tarih ifadelerini çöz) ---
        tool_prompt = SQL_ARCHITECT_PROMPT.format(
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

        messages = [HumanMessage(content=tool_prompt)]
        resolved_dates: Dict[str, str] = {}

        for round_num in range(MAX_TOOL_ROUNDS):
            response = await llm_with_tools.ainvoke(messages)

            if not response.tool_calls:
                logger.info(f"[SQL_ARCHITECT] No tool calls in round {round_num + 1}, proceeding")
                break

            messages.append(response)
            for tc in response.tool_calls:
                tool_name = tc.get("name", "")
                if tool_name == "resolve_date":
                    result = resolve_date.invoke(tc["args"])
                    expression = tc["args"].get("expression", "?")
                    resolved_dates[expression] = result
                    logger.info(f"[SQL_ARCHITECT] Tool call: resolve_date('{expression}') → {result}")
                    messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

        # --- Aşama 2: Resolved date'leri context'e ekle, QuerySchema üret ---
        if resolved_dates:
            resolved_summary = "\n".join(
                f'- "{expr}" → {sql}' for expr, sql in resolved_dates.items()
            )
            final_prompt = tool_prompt + f"\n\n## ÇÖZÜLMÜŞ TARİH İFADELERİ\n{resolved_summary}\n\nBu tarih ifadelerini SchemaFilter'lara uygula."
        else:
            final_prompt = tool_prompt

        logger.info(
            f"[SQL_ARCHITECT] Building schema: {user_query[:80]} "
            f"(type={query_type}, resolved_dates={len(resolved_dates)})"
        )
        schema: QuerySchema = await structured_llm.ainvoke(final_prompt)
        logger.info(
            f"[SQL_ARCHITECT] Schema: filters={len(schema.filters)}, "
            f"aggs={len(schema.aggregations)}, group_by={schema.group_by}, "
            f"limit={schema.limit}, rules={schema.applied_rule_ids}"
        )

        return {
            "query_schema": schema.model_dump(),
            "sql_error": None,
        }

    return sql_architect_node
```

**Step 3: Uçtan uca test — Studio'da**

```
"Son 1 senede ödemesi alınan masaların kategorilere göre en çok ciro yapan kategori nedir?"
```

Beklenen log:
```
[SQL_ARCHITECT] Tool call: resolve_date('son 1 yılda') → OP:>= DATEADD(YEAR, -1, '2026-02-24')
[SQL_ARCHITECT] Schema: filters=2, aggs=1, group_by=['CategoryName'], limit=1, rules=[...]
```

Beklenen SQL:
```sql
SELECT TOP 1 [CategoryName],
       SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END) AS [ToplamCiro]
FROM [MasterReportDocumentTable]
WHERE [IsTableActive] = 0
  AND [DocumentDate] >= DATEADD(YEAR, -1, '2026-02-24')
GROUP BY [CategoryName]
ORDER BY [ToplamCiro] DESC
```

**Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat(text2sql): sql_architect uses resolve_date tool-calling loop before structured output"
```
