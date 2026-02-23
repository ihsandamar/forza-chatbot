# Report Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `src/graphs/report_agent/` altında sıfırdan, sade ve native LangGraph patterns kullanan yeni bir report agent inşa etmek.

**Architecture:** Shared-state subgraph pattern. Ana graph + Text2SQL subgraph + Visualization subgraph aynı `ReportState`'i paylaşır. AskUser için `interrupt()` + `Command(resume=...)` native HITL. Max 2 LLM çağrısı/tur.

**Tech Stack:** LangGraph, LangChain, ChatOpenAI, Pydantic v2, pyodbc, Python 3.12

---

## Referans Dosyalar

Yeni kod yazarken bunlara **bak ama kopyalama:**
- `src/graphs/generic_text2sql/nodekit.py` — DB bağlantı pattern'i (pyodbc, async executor)
- `src/graphs/generic_text2sql/prompts.py` — Mevcut SQL prompt örnekleri (Türkçe domain)
- `src/graphs/data_visualization/nodes/` — Visualization node mantığı
- `src/graphs/generic_text2sql/business_rules.json` — Business rules formatı

---

## Task 1: Klasör Yapısı ve __init__.py Dosyaları

**Files:**
- Create: `src/graphs/report_agent/__init__.py`
- Create: `src/graphs/report_agent/subagents/__init__.py`
- Create: `src/graphs/report_agent/subagents/text2sql/__init__.py`
- Create: `src/graphs/report_agent/subagents/visualization/__init__.py`
- Create: `tests/graphs/report_agent/__init__.py`

**Step 1: Klasörleri oluştur**

```bash
mkdir -p src/graphs/report_agent/subagents/text2sql
mkdir -p src/graphs/report_agent/subagents/visualization
mkdir -p tests/graphs/report_agent
```

**Step 2: `__init__.py` dosyalarını oluştur**

`src/graphs/report_agent/__init__.py`:
```python
from .graph import build_report_agent_graph

__all__ = ["build_report_agent_graph"]
```

`src/graphs/report_agent/subagents/__init__.py`:
```python
```

`src/graphs/report_agent/subagents/text2sql/__init__.py`:
```python
from .graph import build_text2sql_graph

__all__ = ["build_text2sql_graph"]
```

`src/graphs/report_agent/subagents/visualization/__init__.py`:
```python
from .graph import build_visualization_graph

__all__ = ["build_visualization_graph"]
```

`tests/graphs/report_agent/__init__.py`:
```python
```

**Step 3: Commit**

```bash
git add src/graphs/report_agent/ tests/graphs/report_agent/
git commit -m "feat(report-agent): scaffold folder structure"
```

---

## Task 2: ReportState

**Files:**
- Create: `src/graphs/report_agent/state.py`
- Create: `tests/graphs/report_agent/test_state.py`

**Step 1: Failing test yaz**

`tests/graphs/report_agent/test_state.py`:
```python
from src.graphs.report_agent.state import ReportState, create_initial_state


def test_initial_state_has_required_keys():
    state = create_initial_state()
    assert state["messages"] == []
    assert state["intent_type"] is None
    assert state["query_type"] is None
    assert state["active_sql"] is None
    assert state["active_results"] is None
    assert state["results"] is None
    assert state["error"] is None


def test_state_intent_type_field_exists():
    state = create_initial_state()
    assert "intent_type" in state


def test_state_use_result_type_field_exists():
    state = create_initial_state()
    assert "use_result_type" in state


def test_state_active_context_fields():
    state = create_initial_state()
    assert "active_sql" in state
    assert "active_results" in state
    assert "active_filters" in state
```

**Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
pytest tests/graphs/report_agent/test_state.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.graphs.report_agent.state'`

**Step 3: `state.py` yaz**

`src/graphs/report_agent/state.py`:
```python
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ReportState(TypedDict):
    # Core
    messages: Annotated[List[BaseMessage], add_messages]
    user_query: str
    session_id: Optional[str]

    # Intent Classification (tek LLM çağrısı)
    intent_type: Optional[str]         # NEW_QUERY | MODIFY_QUERY | USE_RESULT
    query_type: Optional[str]          # SINGLE | RANKING | COMPARISON | TIME_SERIES_COMPARISON
    intent_confidence: Optional[float]
    use_result_type: Optional[str]     # "new_query" | "revisualize"

    # Conversation Context (MODIFY ve USE_RESULT için)
    active_sql: Optional[str]
    active_results: Optional[List[Dict[str, Any]]]
    active_filters: Optional[List[Dict[str, Any]]]

    # Text2SQL I/O (subgraph shared fields)
    sql_queries: Optional[List[str]]
    results: Optional[List[Dict[str, Any]]]
    error: Optional[str]

    # Visualization
    visualization_output: Optional[Dict[str, Any]]

    # Response
    final_response: Optional[str]


def create_initial_state() -> ReportState:
    return ReportState(
        messages=[],
        user_query="",
        session_id=None,
        intent_type=None,
        query_type=None,
        intent_confidence=None,
        use_result_type=None,
        active_sql=None,
        active_results=None,
        active_filters=None,
        sql_queries=None,
        results=None,
        error=None,
        visualization_output=None,
        final_response=None,
    )
```

**Step 4: Testi çalıştır — PASS bekleniyor**

```bash
pytest tests/graphs/report_agent/test_state.py -v
```

Expected: 4 tests PASS

**Step 5: Commit**

```bash
git add src/graphs/report_agent/state.py tests/graphs/report_agent/test_state.py
git commit -m "feat(report-agent): add ReportState with 15 fields"
```

---

## Task 3: Ana Agent Pydantic Modelleri ve Promptları

**Files:**
- Create: `src/graphs/report_agent/prompts.py`
- Create: `tests/graphs/report_agent/test_prompts.py`

**Step 1: Failing testler yaz**

`tests/graphs/report_agent/test_prompts.py`:
```python
import pytest
from pydantic import ValidationError

from src.graphs.report_agent.prompts import (
    IntentClassificationResult,
    SqlModificationResult,
    EntityExtractionResult,
    INTENT_CLASSIFIER_PROMPT,
    SQL_MODIFIER_PROMPT,
    ENTITY_EXTRACTOR_PROMPT,
)


def test_intent_result_valid_new_query():
    result = IntentClassificationResult(
        intent_type="NEW_QUERY",
        query_type="SINGLE",
        confidence=0.95,
    )
    assert result.intent_type == "NEW_QUERY"
    assert result.confidence == 0.95


def test_intent_result_valid_use_result():
    result = IntentClassificationResult(
        intent_type="USE_RESULT",
        query_type="RANKING",
        confidence=0.8,
        use_result_type="new_query",
    )
    assert result.use_result_type == "new_query"


def test_intent_result_invalid_type():
    with pytest.raises(ValidationError):
        IntentClassificationResult(
            intent_type="UNKNOWN_TYPE",
            query_type="SINGLE",
            confidence=0.9,
        )


def test_sql_modification_result():
    result = SqlModificationResult(
        modified_sql="SELECT * FROM t WHERE city = 'Ankara'",
        explanation="Changed filter from Istanbul to Ankara",
    )
    assert "Ankara" in result.modified_sql


def test_entity_extraction_result():
    result = EntityExtractionResult(
        entity_name="iPhone 15",
        entity_type="product",
        new_query_seed="iPhone 15 satış detayları",
    )
    assert result.entity_name == "iPhone 15"


def test_prompts_are_strings():
    assert isinstance(INTENT_CLASSIFIER_PROMPT, str)
    assert isinstance(SQL_MODIFIER_PROMPT, str)
    assert isinstance(ENTITY_EXTRACTOR_PROMPT, str)


def test_prompts_have_placeholders():
    assert "{user_query}" in INTENT_CLASSIFIER_PROMPT
    assert "{conversation_history}" in INTENT_CLASSIFIER_PROMPT
    assert "{active_sql}" in SQL_MODIFIER_PROMPT
    assert "{active_results}" in ENTITY_EXTRACTOR_PROMPT
```

**Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
pytest tests/graphs/report_agent/test_prompts.py -v
```

**Step 3: `prompts.py` yaz**

`src/graphs/report_agent/prompts.py`:
```python
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


# =============================================================================
# PYDANTIC MODELS — Structured LLM Output
# =============================================================================

class IntentClassificationResult(BaseModel):
    """Intent + query type classification result — tek LLM çağrısı."""

    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT"]
    query_type: Literal["SINGLE", "RANKING", "COMPARISON", "TIME_SERIES_COMPARISON"]
    confidence: float
    use_result_type: Optional[Literal["new_query", "revisualize"]] = None
    # MODIFY_QUERY için delta bilgisi
    modification_action: Optional[str] = None   # "add_filter", "remove_filter", "change_limit", "change_order"
    modification_target: Optional[str] = None   # "şehir", "tarih", "limit"
    modification_value: Optional[str] = None    # "Ankara", "2024-01", "50"

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v


class SqlModificationResult(BaseModel):
    """SQL modifier output — MODIFY_QUERY için."""
    modified_sql: str
    explanation: str


class EntityExtractionResult(BaseModel):
    """Entity extractor output — USE_RESULT(A) için."""
    entity_name: str
    entity_type: str   # "product", "branch", "customer", "category" vb.
    new_query_seed: str  # Text2SQL subagent'a gönderilecek yeni sorgu


# =============================================================================
# PROMPTS
# =============================================================================

INTENT_CLASSIFIER_PROMPT = """Sen bir rapor asistanısın. Kullanıcının mesajını analiz edip intent'ini belirle.

## KONUŞMA GEÇMİŞİ
{conversation_history}

## KULLANICI MESAJI
{user_query}

## MEVCUT SORGU DURUMU
- Aktif SQL var mı: {has_active_sql}
- Son sonuç satır sayısı: {result_count}

## KURALLAR

**intent_type:**
- NEW_QUERY: Kullanıcı yeni bir sorgu istiyor, önceki bağlamla ilgisi yok
- MODIFY_QUERY: Önceki sorguyu değiştirmek istiyor (filtre ekle/çıkar, sırala, say)
  → Aktif SQL olmadan MODIFY_QUERY seçme
- USE_RESULT: Önceki SONUÇLARI kullanmak istiyor
  → use_result_type="new_query": Sonuçtaki bir entity için yeni sorgu
  → use_result_type="revisualize": Aynı veriyi farklı göster

**query_type:**
- SINGLE: Tek bir metrik veya liste
- RANKING: Sıralama / top-N / en fazla / en az
- COMPARISON: İki veya daha fazla grubun karşılaştırması
- TIME_SERIES_COMPARISON: Dönemler arası karşılaştırma

**confidence:** 0.0-1.0 arası güven skoru. 0.7 altında kullanıcıya sor.
"""

SQL_MODIFIER_PROMPT = """Mevcut SQL sorgusunu kullanıcının isteğine göre değiştir.

## MEVCUT SQL
{active_sql}

## AKTİF FİLTRELER
{active_filters}

## KULLANICI İSTEĞİ
{modification_request}

## KOLON BİLGİLERİ
{column_metadata}

## KURALLAR
- Sadece istenilen değişikliği yap, geri kalan SQL'i koru
- Yeni bir filtre ekleniyorsa WHERE clause'a ekle
- Limit değişiyorsa sadece TOP/LIMIT değerini güncelle
- ORDER BY değişiyorsa sadece ORDER BY clause'u güncelle
- Geçerli SQL üret, syntax hatası olmasın
"""

ENTITY_EXTRACTOR_PROMPT = """Kullanıcı önceki sorgu sonuçlarından bir entity seçmek istiyor.

## ÖNCEKİ SONUÇLAR (ilk 5 satır)
{active_results}

## KULLANICI İSTEĞİ
{user_query}

## GÖREV
Kullanıcının hangi entity'yi seçtiğini belirle ve o entity için yeni bir sorgu seed'i oluştur.
- entity_name: Seçilen değer (ör: "iPhone 15", "Ankara", "2024-Q1")
- entity_type: Entity türü (product, branch, customer, category, period)
- new_query_seed: Entity için yeni doğal dil sorgu (Text2SQL'e gönderilecek)
"""
```

**Step 4: Testi çalıştır — PASS bekleniyor**

```bash
pytest tests/graphs/report_agent/test_prompts.py -v
```

**Step 5: Commit**

```bash
git add src/graphs/report_agent/prompts.py tests/graphs/report_agent/test_prompts.py
git commit -m "feat(report-agent): add Pydantic models and 3 core prompts"
```

---

## Task 4: Text2SQL Subagent — State ve Promptlar

**Files:**
- Create: `src/graphs/report_agent/subagents/text2sql/state.py`
- Create: `src/graphs/report_agent/subagents/text2sql/prompts.py`
- Create: `tests/graphs/report_agent/test_text2sql_prompts.py`

**Step 1: Failing test yaz**

`tests/graphs/report_agent/test_text2sql_prompts.py`:
```python
from pydantic import ValidationError
import pytest

from src.graphs.report_agent.subagents.text2sql.prompts import (
    QueryPlan,
    QueryFilter,
    QueryAggregation,
    QUERY_PLANNER_PROMPT,
    SQL_GENERATOR_PROMPT,
    SQL_FIX_PROMPT,
)


def test_query_plan_simple():
    plan = QueryPlan(
        description="En çok satan 10 ürün",
        select_columns=["urun_adi", "toplam_satis"],
        filters=[],
        aggregations=[
            QueryAggregation(function="SUM", field_hint="miktar", alias="toplam_satis")
        ],
        group_by=["urun_adi"],
        order_by_field="toplam_satis",
        order_by_direction="DESC",
        limit=10,
    )
    assert plan.limit == 10
    assert len(plan.aggregations) == 1


def test_query_filter():
    f = QueryFilter(field_hint="sehir", operator="=", value_hint="Istanbul")
    assert f.operator == "="


def test_prompts_have_placeholders():
    assert "{user_query}" in QUERY_PLANNER_PROMPT
    assert "{column_metadata}" in QUERY_PLANNER_PROMPT
    assert "{query_plan}" in SQL_GENERATOR_PROMPT
    assert "{table_name}" in SQL_GENERATOR_PROMPT
    assert "{failed_sql}" in SQL_FIX_PROMPT
    assert "{error_message}" in SQL_FIX_PROMPT
```

**Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
pytest tests/graphs/report_agent/test_text2sql_prompts.py -v
```

**Step 3: `state.py` ve `prompts.py` yaz**

`src/graphs/report_agent/subagents/text2sql/state.py`:
```python
from typing import Any, Dict, List, Optional, TypedDict


class Text2SQLInternalState(TypedDict, total=False):
    """
    Text2SQL subagent'ın iç state'i.

    ReportState'teki shared field'lar (user_query, sql_queries, results, error)
    doğrudan kullanılır. Bu TypedDict sadece subgraph-internal field'lar içindir.
    """
    query_plan: Optional[Dict[str, Any]]   # QueryPlan dict (architect output)
    retry_count: Optional[int]             # SQL fix retry sayacı (max 2)
    sql_error: Optional[str]               # En son SQL hata mesajı
```

`src/graphs/report_agent/subagents/text2sql/prompts.py`:
```python
from typing import List, Literal, Optional

from pydantic import BaseModel


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class QueryFilter(BaseModel):
    field_hint: str
    operator: Literal["=", ">", "<", ">=", "<=", "!=", "LIKE", "IN", "BETWEEN", "IS NULL", "IS NOT NULL"]
    value_hint: str
    logical_operator: Literal["AND", "OR"] = "AND"


class QueryAggregation(BaseModel):
    function: Literal["SUM", "COUNT", "AVG", "MAX", "MIN"]
    field_hint: str
    alias: str


class QueryPlan(BaseModel):
    """SQL Architect'in structured output'u."""
    description: str
    select_columns: List[str]          # Gösterilecek kolonlar (aggregation yoksa)
    filters: List[QueryFilter]
    aggregations: List[QueryAggregation]
    group_by: List[str]
    order_by_field: Optional[str] = None
    order_by_direction: Literal["ASC", "DESC"] = "DESC"
    limit: Optional[int] = None


class GeneratedSQL(BaseModel):
    """SQL Generator'ın output'u."""
    sql: str
    explanation: str


class FixedSQL(BaseModel):
    """SQL Fix node'unun output'u."""
    sql: str
    fix_explanation: str


# =============================================================================
# PROMPTS
# =============================================================================

QUERY_PLANNER_PROMPT = """Sen bir SQL planlama uzmanısın. Kullanıcının sorusunu analiz et ve yapılandırılmış bir sorgu planı çıkar.

## KULLANICI SORUSU
{user_query}

## SORGU TİPİ
{query_type}

## MEVCUT KOLON BİLGİLERİ
{column_metadata}

## BUSINESS RULES
{business_rules}

## CONVERSATION CONTEXT
{conversation_context}

## KURALLAR
- field_hint'ler kolon metadata'sındaki kolon açıklamalarından seç
- value_hint'leri kullanıcının yazdığı gibi bırak (büyük/küçük harf, Türkçe karakter önemli değil)
- RANKING sorguları için mutlaka aggregation + limit ekle
- COMPARISON sorguları için GROUP BY ile segmentleri ayır
- TIME_SERIES için tarih kolonunu GROUP BY'a ekle
"""

SQL_GENERATOR_PROMPT = """Sorgu planına göre geçerli SQL üret.

## TABLO ADI
{table_name}

## KOLON METADATA (gerçek kolon isimleri ve tipleri)
{column_metadata}

## SORGU PLANI
{query_plan}

## DIALECT
Microsoft SQL Server (T-SQL)

## KURALLAR
- Kolon isimlerini metadata'daki GERÇEK isimlerle eşleştir (field_hint → actual column name)
- value_hint'leri fuzzy match için LIKE veya tam eşleşme için = kullan
- String değerler için: önce tam eşleşme dene, olmayacaksa LIKE '%{value}%'
- TOP N kullan (LIMIT değil — T-SQL)
- NULL değerleri göz önünde bulundur
- Tarih filtreleri için: CONVERT veya CAST kullan, string karşılaştırma yapma
- Kolon adlarında boşluk varsa [köşeli parantez] kullan
"""

SQL_FIX_PROMPT = """SQL sorgusu hata verdi. Hatayı düzelt.

## BAŞARISIZ SQL
{failed_sql}

## HATA MESAJI
{error_message}

## TABLO ADI
{table_name}

## KOLON METADATA
{column_metadata}

## SORGU PLANI (orijinal niyet)
{query_plan}

## GÖREV
Hatayı analiz et ve düzeltilmiş SQL üret. Orijinal sorgunun amacını koru.
Yaygın hatalar: yanlış kolon adı, tip uyumsuzluğu, syntax hatası, NULL hatası.
"""
```

**Step 4: Testi çalıştır — PASS bekleniyor**

```bash
pytest tests/graphs/report_agent/test_text2sql_prompts.py -v
```

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/
tests/graphs/report_agent/test_text2sql_prompts.py
git commit -m "feat(report-agent/text2sql): add state and prompts with Pydantic models"
```

---

## Task 5: Text2SQL Subagent — Nodes

**Files:**
- Create: `src/graphs/report_agent/subagents/text2sql/nodes.py`
- Create: `tests/graphs/report_agent/test_text2sql_nodes.py`

**Step 1: Failing testler yaz**

`tests/graphs/report_agent/test_text2sql_nodes.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.graphs.report_agent.subagents.text2sql.nodes import (
    create_query_planner_node,
    create_sql_generator_node,
    create_sql_executor_node,
)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    structured = AsyncMock()
    llm.with_structured_output.return_value = structured
    return llm, structured


@pytest.mark.asyncio
async def test_query_planner_returns_query_plan(mock_llm):
    llm, structured_llm = mock_llm
    from src.graphs.report_agent.subagents.text2sql.prompts import QueryPlan, QueryAggregation

    mock_plan = QueryPlan(
        description="En çok satan ürünler",
        select_columns=[],
        filters=[],
        aggregations=[QueryAggregation(function="SUM", field_hint="miktar", alias="toplam")],
        group_by=["urun_adi"],
        order_by_field="toplam",
        order_by_direction="DESC",
        limit=10,
    )
    structured_llm.ainvoke.return_value = mock_plan

    node_fn = create_query_planner_node(llm, column_metadata={}, business_rules={})

    state = {
        "user_query": "En çok satan 10 ürün",
        "query_type": "RANKING",
        "active_sql": None,
        "active_filters": None,
    }
    result = await node_fn(state)

    assert "query_plan" in result
    assert result["query_plan"]["limit"] == 10


@pytest.mark.asyncio
async def test_sql_generator_returns_sql(mock_llm):
    llm, structured_llm = mock_llm
    from src.graphs.report_agent.subagents.text2sql.prompts import GeneratedSQL

    structured_llm.ainvoke.return_value = GeneratedSQL(
        sql="SELECT TOP 10 urun_adi, SUM(miktar) AS toplam FROM SatisTable GROUP BY urun_adi ORDER BY toplam DESC",
        explanation="Top 10 products by quantity",
    )

    node_fn = create_sql_generator_node(llm, table_name="SatisTable", column_metadata={})

    state = {
        "user_query": "En çok satan 10 ürün",
        "query_plan": {"description": "top 10", "limit": 10},
    }
    result = await node_fn(state)

    assert "sql_queries" in result
    assert len(result["sql_queries"]) == 1
    assert "SatisTable" in result["sql_queries"][0]


@pytest.mark.asyncio
async def test_sql_executor_handles_empty_result():
    with patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._execute_sql",
        new_callable=AsyncMock,
        return_value=[],
    ):
        node_fn = create_sql_executor_node(connection_string="DRIVER=;SERVER=test")
        state = {"sql_queries": ["SELECT TOP 10 * FROM t"], "retry_count": 0}
        result = await node_fn(state)

        assert result["results"] == []
        assert result.get("error") is None
```

**Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
pytest tests/graphs/report_agent/test_text2sql_nodes.py -v
```

**Step 3: `nodes.py` yaz**

`src/graphs/report_agent/subagents/text2sql/nodes.py`:
```python
import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

import pyodbc
from langchain_core.runnables import RunnableConfig

from src.graphs.report_agent.subagents.text2sql.prompts import (
    FixedSQL,
    GeneratedSQL,
    QueryPlan,
    QUERY_PLANNER_PROMPT,
    SQL_GENERATOR_PROMPT,
    SQL_FIX_PROMPT,
)

logger = logging.getLogger(__name__)

_db_executor = ThreadPoolExecutor(max_workers=3)
MAX_RETRY = 2


def _serialize_results(rows: List[Any], columns: List[str]) -> List[Dict[str, Any]]:
    """pyodbc Row → dict list, Decimal ve None güvenli."""
    result = []
    for row in rows:
        record = {}
        for col, val in zip(columns, row):
            if isinstance(val, Decimal):
                val = float(val)
            record[col] = val
        result.append(record)
    return result


async def _execute_sql(connection_string: str, sql: str) -> List[Dict[str, Any]]:
    """SQL'i thread pool'da async çalıştır."""
    loop = asyncio.get_event_loop()

    def _run():
        conn = pyodbc.connect(connection_string, timeout=30)
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        return _serialize_results(rows, columns)

    return await loop.run_in_executor(_db_executor, _run)


def create_query_planner_node(
    llm,
    column_metadata: Dict[str, Any],
    business_rules: Dict[str, Any],
) -> Callable:
    """
    SQL Architect: user_query → structured QueryPlan.
    LLM structured output kullanır.
    """
    structured_llm = llm.with_structured_output(QueryPlan)

    async def query_planner_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        user_query = state.get("user_query", "")
        query_type = state.get("query_type", "SINGLE")
        active_sql = state.get("active_sql")
        active_filters = state.get("active_filters")

        conversation_context = ""
        if active_sql:
            conversation_context = f"Önceki SQL: {active_sql[:300]}"
        if active_filters:
            conversation_context += f"\nAktif filtreler: {json.dumps(active_filters, ensure_ascii=False)}"

        prompt = QUERY_PLANNER_PROMPT.format(
            user_query=user_query,
            query_type=query_type,
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
            business_rules=json.dumps(business_rules, ensure_ascii=False, indent=2),
            conversation_context=conversation_context or "Yeni sorgu, önceki bağlam yok.",
        )

        logger.info(f"[QUERY_PLANNER] Planning for: {user_query[:80]}")
        plan: QueryPlan = await structured_llm.ainvoke(prompt)

        logger.info(
            f"[QUERY_PLANNER] Plan: {plan.description}, "
            f"filters={len(plan.filters)}, aggs={len(plan.aggregations)}, limit={plan.limit}"
        )
        return {"query_plan": plan.model_dump()}

    return query_planner_node


def create_sql_generator_node(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
) -> Callable:
    """
    SQL Builder: QueryPlan → SQL string.
    """
    structured_llm = llm.with_structured_output(GeneratedSQL)

    async def sql_generator_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        query_plan = state.get("query_plan", {})

        prompt = SQL_GENERATOR_PROMPT.format(
            table_name=table_name,
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
            query_plan=json.dumps(query_plan, ensure_ascii=False, indent=2),
        )

        logger.info(f"[SQL_GENERATOR] Generating SQL for table: {table_name}")
        generated: GeneratedSQL = await structured_llm.ainvoke(prompt)

        logger.info(f"[SQL_GENERATOR] SQL: {generated.sql[:150]}")
        return {"sql_queries": [generated.sql]}

    return sql_generator_node


def create_sql_executor_node(connection_string: str, llm=None, column_metadata: Dict = None) -> Callable:
    """
    SQL Executor: SQL çalıştır, hata varsa LLM ile fix et (max 2 retry).
    """
    structured_llm = llm.with_structured_output(FixedSQL) if llm else None

    async def sql_executor_node(state: dict, config: Optional[RunnableConfig] = None) -> dict:
        sql_queries = state.get("sql_queries", [])
        if not sql_queries:
            return {"error": "No SQL to execute"}

        sql = sql_queries[0]
        retry_count = state.get("retry_count", 0)

        try:
            results = await _execute_sql(connection_string, sql)
            logger.info(f"[SQL_EXECUTOR] Success: {len(results)} rows")
            return {
                "results": results,
                "error": None,
                "retry_count": 0,
                # Conversation context güncelle
                "active_sql": sql,
                "active_filters": state.get("active_filters"),
                "active_results": results[:10] if results else [],
            }
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"[SQL_EXECUTOR] Error (attempt {retry_count + 1}): {error_msg[:200]}")

            if structured_llm and retry_count < MAX_RETRY:
                # LLM ile fix et
                fix_prompt = SQL_FIX_PROMPT.format(
                    failed_sql=sql,
                    error_message=error_msg,
                    table_name="(unknown)",
                    column_metadata=json.dumps(column_metadata or {}, ensure_ascii=False),
                    query_plan=json.dumps(state.get("query_plan", {}), ensure_ascii=False),
                )
                fixed: FixedSQL = await structured_llm.ainvoke(fix_prompt)
                logger.info(f"[SQL_EXECUTOR] Fixed SQL: {fixed.sql[:150]}")
                return {
                    "sql_queries": [fixed.sql],
                    "retry_count": retry_count + 1,
                    "sql_error": error_msg,
                }
            else:
                return {
                    "error": f"SQL execution failed after {retry_count} retries: {error_msg}",
                    "results": [],
                }

    return sql_executor_node
```

**Step 4: Testi çalıştır — PASS bekleniyor**

```bash
pytest tests/graphs/report_agent/test_text2sql_nodes.py -v
```

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py \
        tests/graphs/report_agent/test_text2sql_nodes.py
git commit -m "feat(report-agent/text2sql): add query_planner, sql_generator, sql_executor nodes"
```

---

## Task 6: Text2SQL Subagent — Graph

**Files:**
- Create: `src/graphs/report_agent/subagents/text2sql/graph.py`
- Create: `tests/graphs/report_agent/test_text2sql_graph.py`

**Step 1: Failing test yaz**

`tests/graphs/report_agent/test_text2sql_graph.py`:
```python
from unittest.mock import MagicMock

from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph


def test_graph_builds_without_error():
    mock_llm = MagicMock()
    graph = build_text2sql_graph(
        llm=mock_llm,
        table_name="TestTable",
        column_metadata={"id": {"type": "int"}, "name": {"type": "str"}},
        business_rules={},
        connection_string="DRIVER=;SERVER=test",
    )
    assert graph is not None


def test_graph_has_correct_nodes():
    mock_llm = MagicMock()
    graph = build_text2sql_graph(
        llm=mock_llm,
        table_name="TestTable",
        column_metadata={},
        business_rules={},
        connection_string="DRIVER=;SERVER=test",
    )
    # LangGraph compiled graph has get_graph() method
    mermaid = graph.get_graph().draw_mermaid()
    assert "query_planner" in mermaid
    assert "sql_generator" in mermaid
    assert "sql_executor" in mermaid
```

**Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
pytest tests/graphs/report_agent/test_text2sql_graph.py -v
```

**Step 3: `graph.py` yaz**

`src/graphs/report_agent/subagents/text2sql/graph.py`:
```python
import logging
from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.state import ReportState
from src.graphs.report_agent.subagents.text2sql.nodes import (
    create_query_planner_node,
    create_sql_executor_node,
    create_sql_generator_node,
)

logger = logging.getLogger(__name__)


def _route_after_executor(state: dict) -> str:
    """Retry gerekiyorsa sql_generator'a geri dön, değilse END."""
    retry_count = state.get("retry_count", 0)
    sql_error = state.get("sql_error")

    if sql_error and retry_count > 0 and retry_count <= 2:
        logger.info(f"[TEXT2SQL] Retrying SQL (attempt {retry_count})")
        return "sql_generator"
    return END


def build_text2sql_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    business_rules: Dict[str, Any],
    connection_string: str,
):
    """
    Text2SQL subgraph: user_query → results

    Nodes:
        query_planner  → LLM: sorgu planı çıkar
        sql_generator  → LLM: SQL üret
        sql_executor   → pyodbc: çalıştır, hata varsa retry

    Shared State: ReportState (parent ile aynı)
    """
    graph = StateGraph(ReportState)

    # Node factories
    query_planner = create_query_planner_node(llm, column_metadata, business_rules)
    sql_generator = create_sql_generator_node(llm, table_name, column_metadata)
    sql_executor = create_sql_executor_node(connection_string, llm=llm, column_metadata=column_metadata)

    graph.add_node("query_planner", query_planner)
    graph.add_node("sql_generator", sql_generator)
    graph.add_node("sql_executor", sql_executor)

    graph.add_edge(START, "query_planner")
    graph.add_edge("query_planner", "sql_generator")
    graph.add_conditional_edges(
        "sql_executor",
        _route_after_executor,
        {"sql_generator": "sql_generator", END: END},
    )
    graph.add_edge("sql_generator", "sql_executor")

    logger.info("[TEXT2SQL] Graph built: query_planner → sql_generator → sql_executor (max 2 retry)")
    return graph.compile()
```

**Step 4: Testi çalıştır — PASS bekleniyor**

```bash
pytest tests/graphs/report_agent/test_text2sql_graph.py -v
```

**Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/graph.py \
        tests/graphs/report_agent/test_text2sql_graph.py
git commit -m "feat(report-agent/text2sql): add 3-node graph with retry routing"
```

---

## Task 7: Visualization Subagent — Nodes ve Graph

**Files:**
- Create: `src/graphs/report_agent/subagents/visualization/prompts.py`
- Create: `src/graphs/report_agent/subagents/visualization/nodes.py`
- Create: `src/graphs/report_agent/subagents/visualization/graph.py`
- Create: `tests/graphs/report_agent/test_visualization.py`

**Step 1: Failing testler yaz**

`tests/graphs/report_agent/test_visualization.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.graphs.report_agent.subagents.visualization.nodes import (
    data_analyzer_node,
    create_viz_decider_node,
    create_chart_generator_node,
    build_response_node,
)
from src.graphs.report_agent.subagents.visualization.graph import build_visualization_graph


@pytest.mark.asyncio
async def test_data_analyzer_profiles_results():
    state = {
        "results": [
            {"urun": "A", "satis": 100},
            {"urun": "B", "satis": 200},
        ],
        "user_query": "Ürün satışları",
    }
    result = await data_analyzer_node(state)
    assert "data_profile" in result
    assert result["data_profile"]["row_count"] == 2
    assert result["data_profile"]["column_count"] == 2


@pytest.mark.asyncio
async def test_data_analyzer_empty_results():
    state = {"results": [], "user_query": "test"}
    result = await data_analyzer_node(state)
    assert result["data_profile"]["row_count"] == 0


def test_visualization_graph_builds():
    mock_llm = MagicMock()
    graph = build_visualization_graph(llm=mock_llm)
    assert graph is not None
    mermaid = graph.get_graph().draw_mermaid()
    assert "data_analyzer" in mermaid
    assert "viz_decider" in mermaid
    assert "chart_generator" in mermaid
```

**Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
pytest tests/graphs/report_agent/test_visualization.py -v
```

**Step 3: `prompts.py` yaz**

`src/graphs/report_agent/subagents/visualization/prompts.py`:
```python
from typing import Literal, Optional

from pydantic import BaseModel


class VizDecision(BaseModel):
    """Visualization decider output."""
    needs_graph: bool
    chart_type: Literal[
        "bar_chart", "line_chart", "pie_chart",
        "table", "single_value", "kpi_cards",
        "scatter_chart", "comparison"
    ]
    x_field: Optional[str] = None
    y_field: Optional[str] = None
    label_field: Optional[str] = None
    value_field: Optional[str] = None
    title: Optional[str] = None
    reason: str


class PlotlyCode(BaseModel):
    """Chart generator output."""
    plotly_json: str   # JSON string of Plotly figure dict
    html_snippet: str  # Embeddable <div> + script


VIZ_DECIDER_PROMPT = """Veri analiz sonucuna göre en uygun görselleştirmeyi seç.

## KULLANICI SORUSU
{user_query}

## VERİ PROFİLİ
- Satır sayısı: {row_count}
- Kolon sayısı: {column_count}
- Kolonlar: {columns}
- Sayısal kolonlar: {numeric_columns}
- Metin kolonlar: {text_columns}
- Örnek veri: {sample_rows}

## SORGU TİPİ
{query_type}

## KARAR KURALLARI
- Tek sayısal değer → single_value veya kpi_cards
- 2-10 kategori + sayı → bar_chart
- Zaman serisi → line_chart
- Oran/yüzde → pie_chart
- Çok satır liste → table
- Karşılaştırma → comparison veya bar_chart
- needs_graph=False sadece düz metin cevap yeterliyse

x_field ve y_field için kolonların GERÇEK adlarını kullan.
"""

CHART_GENERATOR_PROMPT = """Plotly figürü için JSON üret.

## KULLANICI SORUSU
{user_query}

## VİZUALİZASYON KARARI
{viz_decision}

## VERİ (tüm satırlar)
{data}

## KURALLAR
- plotly_json: Geçerli JSON string (json.loads ile parse edilebilmeli)
- Plotly layout'ta: autosize=True, responsive layout
- Türkçe karakter içeren title/label'lar desteklenmeli
- html_snippet: <div id="chart-{chart_id}"></div> + inline <script> içeren snippet
- chart_id için rastgele 6 haneli hex kullan
"""
```

**Step 4: `nodes.py` yaz**

`src/graphs/report_agent/subagents/visualization/nodes.py`:
```python
import json
import logging
import random
import string
from typing import Any, Callable, Dict, List, Optional

from src.graphs.report_agent.subagents.visualization.prompts import (
    ChartGenerator,
    PlotlyCode,
    VizDecision,
    CHART_GENERATOR_PROMPT,
    VIZ_DECIDER_PROMPT,
)

logger = logging.getLogger(__name__)


def _profile_data(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure Python: veri profilini çıkar, LLM yok."""
    if not results:
        return {
            "row_count": 0,
            "column_count": 0,
            "columns": [],
            "numeric_columns": [],
            "text_columns": [],
            "sample_rows": [],
        }

    columns = list(results[0].keys())
    numeric_columns = [
        col for col in columns
        if any(isinstance(row.get(col), (int, float)) for row in results[:5])
    ]
    text_columns = [col for col in columns if col not in numeric_columns]

    return {
        "row_count": len(results),
        "column_count": len(columns),
        "columns": columns,
        "numeric_columns": numeric_columns,
        "text_columns": text_columns,
        "sample_rows": results[:3],
    }


async def data_analyzer_node(state: dict) -> dict:
    """Pure Python: result'ı profille. LLM çağrısı yok."""
    results = state.get("results") or []
    profile = _profile_data(results)
    logger.info(f"[VIZ] Data profile: {profile['row_count']} rows, {profile['column_count']} cols")
    return {"data_profile": profile}


def create_viz_decider_node(llm) -> Callable:
    """LLM: veri profiline göre chart type karar ver."""
    structured_llm = llm.with_structured_output(VizDecision)

    async def viz_decider_node(state: dict) -> dict:
        results = state.get("results") or []
        if not results:
            logger.info("[VIZ] No results, skipping visualization")
            return {
                "visualization_output": {
                    "needs_graph": False,
                    "chart_type": "table",
                    "reason": "No data",
                }
            }

        profile = state.get("data_profile", _profile_data(results))

        prompt = VIZ_DECIDER_PROMPT.format(
            user_query=state.get("user_query", ""),
            row_count=profile["row_count"],
            column_count=profile["column_count"],
            columns=", ".join(profile["columns"]),
            numeric_columns=", ".join(profile["numeric_columns"]),
            text_columns=", ".join(profile["text_columns"]),
            sample_rows=json.dumps(profile["sample_rows"], ensure_ascii=False),
            query_type=state.get("query_type", "SINGLE"),
        )

        decision: VizDecision = await structured_llm.ainvoke(prompt)
        logger.info(f"[VIZ] Decision: {decision.chart_type}, needs_graph={decision.needs_graph}")
        return {"viz_decision": decision.model_dump()}

    return viz_decider_node


def create_chart_generator_node(llm) -> Callable:
    """LLM: Plotly JSON + HTML snippet üret."""
    structured_llm = llm.with_structured_output(PlotlyCode)

    async def chart_generator_node(state: dict) -> dict:
        viz_decision = state.get("viz_decision", {})
        if not viz_decision.get("needs_graph", False):
            logger.info("[VIZ] No graph needed, skipping chart generation")
            return {}

        results = state.get("results") or []
        chart_id = "".join(random.choices(string.hexdigits[:16], k=6))

        prompt = CHART_GENERATOR_PROMPT.format(
            user_query=state.get("user_query", ""),
            viz_decision=json.dumps(viz_decision, ensure_ascii=False),
            data=json.dumps(results, ensure_ascii=False),
            chart_id=chart_id,
        )

        plotly_output: PlotlyCode = await structured_llm.ainvoke(prompt)
        logger.info("[VIZ] Plotly code generated")
        return {
            "plotly_json": plotly_output.plotly_json,
            "plotly_html_snippet": plotly_output.html_snippet,
        }

    return chart_generator_node


async def build_response_node(state: dict) -> dict:
    """Pure Python: visualization_output'u assemble et."""
    viz_decision = state.get("viz_decision", {})
    results = state.get("results") or []

    visualization_output = {
        "needs_graph": viz_decision.get("needs_graph", False),
        "chart_type": viz_decision.get("chart_type", "table"),
        "data": results,
        "plotly_html_snippet": state.get("plotly_html_snippet"),
        "plotly_json": state.get("plotly_json"),
        "title": viz_decision.get("title", ""),
    }

    return {"visualization_output": visualization_output}
```

**Step 5: `graph.py` yaz**

`src/graphs/report_agent/subagents/visualization/graph.py`:
```python
import logging

from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.state import ReportState
from src.graphs.report_agent.subagents.visualization.nodes import (
    build_response_node,
    create_chart_generator_node,
    create_viz_decider_node,
    data_analyzer_node,
)

logger = logging.getLogger(__name__)


def build_visualization_graph(llm):
    """
    Visualization subgraph: results → visualization_output

    Nodes:
        data_analyzer  → Pure Python: veri profili
        viz_decider    → LLM: chart type karar
        chart_generator → LLM: Plotly JSON üret
        build_response → Pure Python: output assemble

    Shared State: ReportState (parent ile aynı)
    """
    graph = StateGraph(ReportState)

    viz_decider = create_viz_decider_node(llm)
    chart_generator = create_chart_generator_node(llm)

    graph.add_node("data_analyzer", data_analyzer_node)
    graph.add_node("viz_decider", viz_decider)
    graph.add_node("chart_generator", chart_generator)
    graph.add_node("build_response", build_response_node)

    graph.add_edge(START, "data_analyzer")
    graph.add_edge("data_analyzer", "viz_decider")
    graph.add_edge("viz_decider", "chart_generator")
    graph.add_edge("chart_generator", "build_response")
    graph.add_edge("build_response", END)

    logger.info("[VIZ] Graph built: data_analyzer → viz_decider → chart_generator → build_response")
    return graph.compile()
```

**Step 6: Testi çalıştır — PASS bekleniyor**

```bash
pytest tests/graphs/report_agent/test_visualization.py -v
```

**Step 7: Commit**

```bash
git add src/graphs/report_agent/subagents/visualization/ \
        tests/graphs/report_agent/test_visualization.py
git commit -m "feat(report-agent/visualization): add 4-node visualization subgraph"
```

---

## Task 8: Ana Agent — Nodes

**Files:**
- Create: `src/graphs/report_agent/nodes.py`
- Create: `tests/graphs/report_agent/test_nodes.py`

**Step 1: Failing testler yaz**

`tests/graphs/report_agent/test_nodes.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.graphs.report_agent.nodes import (
    create_classify_intent_node,
    create_modify_sql_node,
    create_extract_entity_node,
    build_response_node,
)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    structured = AsyncMock()
    llm.with_structured_output.return_value = structured
    return llm, structured


@pytest.mark.asyncio
async def test_classify_intent_new_query(mock_llm):
    from src.graphs.report_agent.prompts import IntentClassificationResult
    llm, structured_llm = mock_llm
    structured_llm.ainvoke.return_value = IntentClassificationResult(
        intent_type="NEW_QUERY",
        query_type="RANKING",
        confidence=0.95,
    )

    node_fn = create_classify_intent_node(llm)
    state = {
        "user_query": "En çok satan 10 ürün",
        "messages": [],
        "active_sql": None,
        "active_results": None,
        "results": None,
    }
    result = await node_fn(state)

    assert result["intent_type"] == "NEW_QUERY"
    assert result["query_type"] == "RANKING"
    assert result["intent_confidence"] == 0.95


@pytest.mark.asyncio
async def test_classify_intent_modify_query(mock_llm):
    from src.graphs.report_agent.prompts import IntentClassificationResult
    llm, structured_llm = mock_llm
    structured_llm.ainvoke.return_value = IntentClassificationResult(
        intent_type="MODIFY_QUERY",
        query_type="RANKING",
        confidence=0.9,
        modification_action="add_filter",
        modification_target="şehir",
        modification_value="Ankara",
    )

    node_fn = create_classify_intent_node(llm)
    state = {
        "user_query": "Şimdi sadece Ankara'yı göster",
        "messages": [],
        "active_sql": "SELECT TOP 10 * FROM t",
        "active_results": None,
        "results": None,
    }
    result = await node_fn(state)
    assert result["intent_type"] == "MODIFY_QUERY"


@pytest.mark.asyncio
async def test_build_response_assembles_final_response():
    state = {
        "results": [{"urun": "A", "satis": 100}],
        "visualization_output": {"needs_graph": True, "plotly_html_snippet": "<div>chart</div>"},
        "error": None,
        "user_query": "En çok satan ürün",
    }
    result = await build_response_node(state)
    assert "final_response" in result
    assert result["final_response"] is not None
```

**Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
pytest tests/graphs/report_agent/test_nodes.py -v
```

**Step 3: `nodes.py` yaz**

`src/graphs/report_agent/nodes.py`:
```python
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
    """
    Intent Classifier: user_query → intent_type + query_type.

    Confidence < 0.70 ise interrupt() ile kullanıcıya sorar.
    """
    structured_llm = llm.with_structured_output(IntentClassificationResult)

    async def classify_intent_node(state: dict) -> dict:
        user_query = state.get("user_query", "")
        active_sql = state.get("active_sql")
        active_results = state.get("active_results") or []
        messages = state.get("messages", [])

        # Konuşma geçmişini özetle (son 4 mesaj)
        history_parts = []
        for msg in messages[-4:]:
            if isinstance(msg, HumanMessage):
                history_parts.append(f"Kullanıcı: {msg.content[:100]}")
            elif isinstance(msg, AIMessage):
                history_parts.append(f"Asistan: {msg.content[:100]}")
        conversation_history = "\n".join(history_parts) if history_parts else "İlk mesaj"

        prompt = INTENT_CLASSIFIER_PROMPT.format(
            user_query=user_query,
            conversation_history=conversation_history,
            has_active_sql="Evet" if active_sql else "Hayır",
            result_count=len(active_results),
        )

        logger.info(f"[CLASSIFY_INTENT] Query: {user_query[:80]}")
        result: IntentClassificationResult = await structured_llm.ainvoke(prompt)
        logger.info(
            f"[CLASSIFY_INTENT] → {result.intent_type}/{result.query_type} "
            f"(confidence={result.confidence:.2f})"
        )

        # Düşük confidence → kullanıcıya sor
        if result.confidence < CONFIDENCE_THRESHOLD:
            logger.warning(f"[CLASSIFY_INTENT] Low confidence ({result.confidence:.2f}), interrupting")
            options = _build_clarification_options(result, active_sql)
            answer = interrupt({
                "type": "confirmation",
                "question": f"'{user_query}' için ne yapmamı istiyorsunuz?",
                "options": options,
            })
            # Kullanıcı cevabına göre intent'i güncelle
            result = _apply_user_answer(result, answer, options)

        return {
            "intent_type": result.intent_type,
            "query_type": result.query_type,
            "intent_confidence": result.confidence,
            "use_result_type": result.use_result_type,
            "messages": [HumanMessage(content=user_query)],
        }

    return classify_intent_node


def _build_clarification_options(result: IntentClassificationResult, active_sql: Optional[str]):
    options = ["Yeni sorgu yap"]
    if active_sql:
        options.append("Mevcut sorguyu değiştir")
    options.append("Sonuçları farklı göster")
    return options


def _apply_user_answer(result: IntentClassificationResult, answer: str, options: list) -> IntentClassificationResult:
    """Kullanıcı cevabına göre intent_type güncelle."""
    if "Yeni sorgu" in answer:
        result.intent_type = "NEW_QUERY"
    elif "değiştir" in answer:
        result.intent_type = "MODIFY_QUERY"
    elif "farklı göster" in answer:
        result.intent_type = "USE_RESULT"
        result.use_result_type = "revisualize"
    result.confidence = 1.0  # Kullanıcı onayladı
    return result


def create_modify_sql_node(llm, column_metadata: dict) -> Callable:
    """
    SQL Modifier: active_sql + modification intent → modified_sql.
    Text2SQL subgraph'ı bypass eder, doğrudan executor'a gider.
    """
    structured_llm = llm.with_structured_output(SqlModificationResult)

    async def modify_sql_node(state: dict) -> dict:
        active_sql = state.get("active_sql", "")
        active_filters = state.get("active_filters") or []
        user_query = state.get("user_query", "")

        if not active_sql:
            logger.warning("[MODIFY_SQL] No active SQL, falling back to new query")
            return {"intent_type": "NEW_QUERY"}

        prompt = SQL_MODIFIER_PROMPT.format(
            active_sql=active_sql,
            active_filters=json.dumps(active_filters, ensure_ascii=False),
            modification_request=user_query,
            column_metadata=json.dumps(column_metadata, ensure_ascii=False, indent=2),
        )

        result: SqlModificationResult = await structured_llm.ainvoke(prompt)
        logger.info(f"[MODIFY_SQL] Modified SQL: {result.modified_sql[:150]}")
        return {"sql_queries": [result.modified_sql]}

    return modify_sql_node


def create_extract_entity_node(llm) -> Callable:
    """
    Entity Extractor: USE_RESULT(A) için önceki result'tan entity çek.
    """
    structured_llm = llm.with_structured_output(EntityExtractionResult)

    async def extract_entity_node(state: dict) -> dict:
        active_results = state.get("active_results") or []
        user_query = state.get("user_query", "")

        if not active_results:
            logger.warning("[EXTRACT_ENTITY] No active results to extract from")
            return {"intent_type": "NEW_QUERY"}

        prompt = ENTITY_EXTRACTOR_PROMPT.format(
            active_results=json.dumps(active_results[:5], ensure_ascii=False, indent=2),
            user_query=user_query,
        )

        result: EntityExtractionResult = await structured_llm.ainvoke(prompt)
        logger.info(f"[EXTRACT_ENTITY] Entity: {result.entity_name} ({result.entity_type})")

        # user_query'yi yeni sorgu seed'i ile güncelle
        return {"user_query": result.new_query_seed}

    return extract_entity_node


async def build_response_node(state: dict) -> dict:
    """
    Final Response Builder: results + visualization_output → final_response.
    Pure Python, LLM yok.
    """
    error = state.get("error")
    results = state.get("results") or []
    viz_output = state.get("visualization_output") or {}

    if error:
        final_response = f"Sorgu çalıştırılırken hata oluştu: {error}"
    elif not results:
        final_response = "Bu sorgu için sonuç bulunamadı."
    else:
        row_count = len(results)
        has_chart = viz_output.get("needs_graph", False)
        chart_html = viz_output.get("plotly_html_snippet", "")

        summary = f"{row_count} sonuç bulundu."
        final_response = chart_html if has_chart else summary

    return {
        "final_response": final_response,
        "messages": [AIMessage(content=final_response)],
    }
```

**Step 4: Testi çalıştır — PASS bekleniyor**

```bash
pytest tests/graphs/report_agent/test_nodes.py -v
```

**Step 5: Commit**

```bash
git add src/graphs/report_agent/nodes.py \
        tests/graphs/report_agent/test_nodes.py
git commit -m "feat(report-agent): add main agent nodes with native interrupt() HITL"
```

---

## Task 9: Ana Agent — Graph

**Files:**
- Create: `src/graphs/report_agent/graph.py`
- Create: `tests/graphs/report_agent/test_graph.py`

**Step 1: Failing testler yaz**

`tests/graphs/report_agent/test_graph.py`:
```python
from unittest.mock import MagicMock

from src.graphs.report_agent.graph import build_report_agent_graph


def test_graph_builds_without_error():
    mock_llm = MagicMock()
    graph = build_report_agent_graph(
        llm=mock_llm,
        table_name="TestTable",
        column_metadata={"id": {"type": "int"}},
        business_rules={},
        connection_string="DRIVER=;SERVER=test",
    )
    assert graph is not None


def test_graph_has_correct_nodes():
    mock_llm = MagicMock()
    graph = build_report_agent_graph(
        llm=mock_llm,
        table_name="TestTable",
        column_metadata={},
        business_rules={},
        connection_string="DRIVER=;SERVER=test",
    )
    mermaid = graph.get_graph(xray=True).draw_mermaid()
    assert "classify_intent" in mermaid
    assert "build_response" in mermaid


def test_graph_routing_keys():
    """intent_router'ın tüm olası path'leri döndürdüğünü kontrol et."""
    from src.graphs.report_agent.graph import _intent_router

    assert _intent_router({"intent_type": "NEW_QUERY"}) == "text2sql"
    assert _intent_router({"intent_type": "MODIFY_QUERY"}) == "modify_sql"
    assert _intent_router({"intent_type": "USE_RESULT", "use_result_type": "new_query"}) == "extract_entity"
    assert _intent_router({"intent_type": "USE_RESULT", "use_result_type": "revisualize"}) == "visualization"
    assert _intent_router({"intent_type": "UNKNOWN"}) == "text2sql"  # Fallback
```

**Step 2: Testi çalıştır — FAIL bekleniyor**

```bash
pytest tests/graphs/report_agent/test_graph.py -v
```

**Step 3: `graph.py` yaz**

`src/graphs/report_agent/graph.py`:
```python
"""
Report Agent — Ana Graph

Architecture:
    START
      ↓
    classify_intent   (LLM + interrupt() HITL)
      ↓
    [intent_router]
      ├── NEW_QUERY      → text2sql → visualization → build_response
      ├── MODIFY_QUERY   → modify_sql → text2sql → visualization → build_response
      ├── USE_RESULT(A)  → extract_entity → text2sql → visualization → build_response
      └── USE_RESULT(B)  → visualization → build_response
                                            ↓
                                          END

Nodes: 6 | LLM çağrısı: max 2/tur | State fields: 15
"""
import logging
from typing import Any, Dict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.graphs.report_agent.nodes import (
    build_response_node,
    create_classify_intent_node,
    create_extract_entity_node,
    create_modify_sql_node,
)
from src.graphs.report_agent.state import ReportState
from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph
from src.graphs.report_agent.subagents.visualization.graph import build_visualization_graph

logger = logging.getLogger(__name__)


def _intent_router(state: dict) -> str:
    """Intent type'a göre routing — pure function, test edilebilir."""
    intent = state.get("intent_type", "NEW_QUERY")
    use_result_type = state.get("use_result_type")

    if intent == "MODIFY_QUERY":
        return "modify_sql"
    if intent == "USE_RESULT":
        if use_result_type == "revisualize":
            return "visualization"
        return "extract_entity"  # use_result_type == "new_query"
    return "text2sql"  # NEW_QUERY + fallback


def build_report_agent_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    business_rules: Dict[str, Any],
    connection_string: str,
    checkpointer=None,
):
    """
    Report Agent ana graph'ı inşa et.

    Args:
        llm: ChatOpenAI veya uyumlu LLM
        table_name: Hedef DB tablo adı
        column_metadata: Kolon isimleri, tipleri, açıklamaları
        business_rules: İş kuralları dict
        connection_string: pyodbc bağlantı string'i
        checkpointer: LangGraph checkpointer (default: MemorySaver)

    Returns:
        Compiled StateGraph
    """
    logger.info(f"[REPORT_AGENT] Building graph for table: {table_name}")

    # Subgraphs (shared ReportState)
    text2sql_subgraph = build_text2sql_graph(
        llm=llm,
        table_name=table_name,
        column_metadata=column_metadata,
        business_rules=business_rules,
        connection_string=connection_string,
    )
    visualization_subgraph = build_visualization_graph(llm=llm)

    # Node factories
    classify_intent_node = create_classify_intent_node(llm)
    modify_sql_node = create_modify_sql_node(llm, column_metadata)
    extract_entity_node = create_extract_entity_node(llm)

    # Graph
    graph = StateGraph(ReportState)

    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("modify_sql", modify_sql_node)
    graph.add_node("extract_entity", extract_entity_node)
    graph.add_node("text2sql", text2sql_subgraph)
    graph.add_node("visualization", visualization_subgraph)
    graph.add_node("build_response", build_response_node)

    # Edges
    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        _intent_router,
        {
            "text2sql": "text2sql",
            "modify_sql": "modify_sql",
            "extract_entity": "extract_entity",
            "visualization": "visualization",
        },
    )
    graph.add_edge("modify_sql", "text2sql")
    graph.add_edge("extract_entity", "text2sql")
    graph.add_edge("text2sql", "visualization")
    graph.add_edge("visualization", "build_response")
    graph.add_edge("build_response", END)

    # Compile
    if checkpointer is None:
        checkpointer = MemorySaver()

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("[REPORT_AGENT] Graph compiled: 6 nodes, max 2 LLM calls/turn")
    return compiled
```

**Step 4: Testi çalıştır — PASS bekleniyor**

```bash
pytest tests/graphs/report_agent/test_graph.py -v
```

**Step 5: Tüm testleri çalıştır**

```bash
pytest tests/graphs/report_agent/ -v
```

Expected: Tüm testler PASS

**Step 6: Commit**

```bash
git add src/graphs/report_agent/graph.py \
        tests/graphs/report_agent/test_graph.py
git commit -m "feat(report-agent): add main orchestrator graph with 6 nodes"
```

---

## Task 10: Integration Smoke Test

**Files:**
- Create: `tests/graphs/report_agent/test_integration.py`

**Step 1: Integration testi yaz**

`tests/graphs/report_agent/test_integration.py`:
```python
"""
Smoke test: Graph doğru build olup state'i doğru işliyor mu?
DB bağlantısı yok, tüm LLM çağrıları mock.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.graphs.report_agent.graph import build_report_agent_graph
from src.graphs.report_agent.prompts import IntentClassificationResult
from src.graphs.report_agent.subagents.text2sql.prompts import QueryPlan, GeneratedSQL
from src.graphs.report_agent.subagents.visualization.prompts import VizDecision


@pytest.fixture
def mock_llm():
    """Her with_structured_output çağrısı için uygun mock döndür."""
    llm = MagicMock()

    def structured_output_factory(schema):
        mock = AsyncMock()

        if schema == IntentClassificationResult:
            mock.ainvoke.return_value = IntentClassificationResult(
                intent_type="NEW_QUERY",
                query_type="RANKING",
                confidence=0.95,
            )
        elif schema == QueryPlan:
            mock.ainvoke.return_value = QueryPlan(
                description="Top 10 products",
                select_columns=[],
                filters=[],
                aggregations=[],
                group_by=["urun"],
                order_by_field="satis",
                limit=10,
            )
        elif schema == GeneratedSQL:
            mock.ainvoke.return_value = GeneratedSQL(
                sql="SELECT TOP 10 urun, SUM(satis) FROM TestTable GROUP BY urun ORDER BY SUM(satis) DESC",
                explanation="Top 10",
            )
        elif schema == VizDecision:
            mock.ainvoke.return_value = VizDecision(
                needs_graph=True,
                chart_type="bar_chart",
                x_field="urun",
                y_field="satis",
                reason="Ranking data suits bar chart",
            )
        else:
            mock.ainvoke.return_value = MagicMock(
                model_dump=lambda: {}, plotly_json="{}", html_snippet="<div></div>"
            )

        return mock

    llm.with_structured_output.side_effect = structured_output_factory
    return llm


@pytest.mark.asyncio
async def test_new_query_flow(mock_llm):
    """NEW_QUERY → text2sql → visualization → build_response akışı."""
    with patch(
        "src.graphs.report_agent.subagents.text2sql.nodes._execute_sql",
        new_callable=AsyncMock,
        return_value=[{"urun": "iPhone", "satis": 500}, {"urun": "Samsung", "satis": 400}],
    ):
        graph = build_report_agent_graph(
            llm=mock_llm,
            table_name="TestTable",
            column_metadata={"urun": {"type": "str"}, "satis": {"type": "int"}},
            business_rules={},
            connection_string="DRIVER=;SERVER=test",
        )

        state = {
            "user_query": "En çok satan 10 ürün",
            "messages": [],
            "active_sql": None,
            "active_results": None,
        }

        config = {"configurable": {"thread_id": "test-thread-1"}}
        result = await graph.ainvoke(state, config=config)

        assert result["intent_type"] == "NEW_QUERY"
        assert result["results"] is not None
        assert len(result["results"]) == 2
        assert result["final_response"] is not None
```

**Step 2: Testi çalıştır — PASS bekleniyor**

```bash
pytest tests/graphs/report_agent/test_integration.py -v
```

**Step 3: Final commit**

```bash
git add tests/graphs/report_agent/test_integration.py
git commit -m "test(report-agent): add integration smoke test"
```

---

## Özet

| Task | Dosya | Test |
|------|-------|------|
| 1 | Folder scaffold | — |
| 2 | `state.py` | `test_state.py` |
| 3 | `prompts.py` | `test_prompts.py` |
| 4 | `text2sql/state.py`, `text2sql/prompts.py` | `test_text2sql_prompts.py` |
| 5 | `text2sql/nodes.py` | `test_text2sql_nodes.py` |
| 6 | `text2sql/graph.py` | `test_text2sql_graph.py` |
| 7 | `visualization/prompts.py`, `visualization/nodes.py`, `visualization/graph.py` | `test_visualization.py` |
| 8 | `nodes.py` | `test_nodes.py` |
| 9 | `graph.py` | `test_graph.py` |
| 10 | — | `test_integration.py` |

**Toplam:** ~10 commit, ~1000 satır yeni kod, ~500 satır test
**Kalan:** Mevcut `src/graphs/report/` silinmesi ve registry güncellemesi — ayrı task olarak yapılacak
