# Term Vector Store Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace deterministic keyword matching in `term_resolver.py` with a ChromaDB-backed semantic vector store (`TermVectorStore`) that uses specificity-based conflict resolution to suppress spurious ambiguity interrupts (e.g., "ne kadar ciro yaptı" must never ask for clarification).

**Architecture:** `TermVectorStore` follows the existing `BusinessRulesVectorStore` pattern: JSON → ChromaDB → semantic embedding at startup, `resolve()` at query time. Conflict resolution ranks candidates by `similarity * specificity`; if an unambiguous high-specificity term already resolved a column, any ambiguous term targeting that column is suppressed and an LLM hint is emitted instead. `term_resolver.py` is deleted entirely.

**Tech Stack:** ChromaDB, `sentence-transformers/all-MiniLM-L6-v2`, dataclasses, pytest + `unittest.mock`

---

### Task 1: Update `term_dictionary.json` to v2.0

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/term_dictionary.json`

No tests needed — pure data.

**Step 1: Replace the entire file with this v2.0 content**

```json
{
  "version": "2.0",
  "description": "Türkçe iş terimi → DB kolon/değer eşleştirme sözlüğü. Tablo bağımsız.",
  "terms": [
    {
      "id": "metric_revenue",
      "category": "metric",
      "term": "ciro",
      "aliases": ["satış tutarı", "gelir", "revenue", "tutar", "satış", "kazanç", "hasılat"],
      "column": "RowAmount",
      "specificity": 1.0,
      "hint": "Satış tutarını temsil eder → aggregations: SUM([RowAmount]) kullan",
      "embedding_text": "Ciro, gelir, hasılat, satış tutarı, para birimi cinsinden satış değeri, toplam tutar"
    },
    {
      "id": "metric_quantity",
      "category": "metric",
      "term": "adet",
      "aliases": ["miktar", "quantity", "satış adedi", "satılan", "kaç tane"],
      "column": "Quantity",
      "specificity": 1.0,
      "hint": "Satış adedini temsil eder → aggregations: SUM([Quantity]) kullan",
      "embedding_text": "Satış adedi, miktar, kaç tane, adet, satılan ürün sayısı"
    },
    {
      "id": "metric_discount",
      "category": "metric",
      "term": "indirim",
      "aliases": ["iskonto", "indirim tutarı", "discount"],
      "column": "DiscountAmountTotal",
      "specificity": 1.0,
      "hint": "İndirim tutarı → aggregations: SUM([DiscountAmountTotal]) veya AVG([DiscountAmountTotal]) kullan",
      "embedding_text": "İndirim tutarı, iskonto miktarı, discount, uygulanan indirim"
    },
    {
      "id": "metric_ambiguous_how_much",
      "category": "metric",
      "term": "ne kadar sattı",
      "aliases": [
        "ne kadar", "sattı", "ne kadar satıldı", "ne kadar oldu",
        "satış miktarı nedir", "toplam satış", "satış bilgisi"
      ],
      "specificity": 0.2,
      "ambiguous_columns": [
        {
          "column": "RowAmount",
          "description": "Satış tutarı (TL)",
          "filter_structured": null
        },
        {
          "column": "Quantity",
          "description": "Satış miktarı (Adet)",
          "filter_structured": null
        }
      ],
      "hint": "Kullanıcı seçimine göre belirlenecek",
      "embedding_text": "Satış miktarı veya tutarı belirsiz soru, ne kadar, hangi ölçüt"
    },
    {
      "id": "dim_document",
      "category": "dimension",
      "term": "adisyon",
      "aliases": ["fiş", "sipariş", "belge", "document"],
      "column": "DocumentId",
      "specificity": 1.0,
      "hint": "Adisyon sayısı için → aggregations: COUNT(DISTINCT [DocumentId]) kullan",
      "embedding_text": "Adisyon, fiş, sipariş belgesi, belge sayısı, document count"
    },
    {
      "id": "dim_category",
      "category": "dimension",
      "term": "kategori",
      "aliases": ["kategoriler", "kategoriye göre", "kategorilere göre", "kategoride", "ürün kategorisi"],
      "column": "CategoryName",
      "specificity": 1.0,
      "hint": "Kategori kolonu → group_by veya select: [CategoryName] kullan",
      "embedding_text": "Kategori, ürün grubu, ürün kategorisi, hangi kategoride"
    },
    {
      "id": "dim_product",
      "category": "dimension",
      "term": "ürün",
      "aliases": ["ürünler", "ürüne göre", "ürünlere göre", "ürün adı", "menü ürünü"],
      "column": "ProductName",
      "specificity": 0.8,
      "hint": "Ürün kolonu → group_by veya select: [ProductName] kullan",
      "embedding_text": "Ürün adı, menü ürünü, yemek, hangi ürün"
    },
    {
      "id": "dim_branch",
      "category": "dimension",
      "term": "şube",
      "aliases": ["şubeler", "şubeye göre", "şubelere göre", "şubede", "lokasyon"],
      "column": "BranchName",
      "specificity": 1.0,
      "hint": "Şube kolonu → group_by veya select: [BranchName] kullan",
      "embedding_text": "Şube, lokasyon, restoran şubesi, hangi şubede"
    },
    {
      "id": "dim_cashier",
      "category": "dimension",
      "term": "kasiyer",
      "aliases": ["kasiyerler", "kasiyere göre", "kasiyerlere göre", "kasiyer adı"],
      "column": "CashierName",
      "specificity": 1.0,
      "hint": "Kasiyer kolonu → group_by veya select: [CashierName] kullan",
      "embedding_text": "Kasiyer adı, ödeme alan, kasiyere göre"
    },
    {
      "id": "dim_table",
      "category": "dimension",
      "term": "masa",
      "aliases": ["masa numarası", "masa no", "table no", "masalar"],
      "column": "TableNo",
      "specificity": 0.7,
      "hint": "Masa numarası kolonu → group_by veya select: [TableNo] kullan",
      "embedding_text": "Masa numarası, hangi masada, table no"
    },
    {
      "id": "dim_city",
      "category": "dimension",
      "term": "şehir",
      "aliases": ["şehirler", "şehre göre", "şehirlere göre", "il"],
      "column": "BranchCityName",
      "specificity": 1.0,
      "hint": "Şehir kolonu → group_by veya select: [BranchCityName] kullan",
      "embedding_text": "Şehir, il, bulunduğu şehir, hangi ilde"
    },
    {
      "id": "dim_customer",
      "category": "dimension",
      "term": "cari",
      "aliases": [
        "cariler", "cariye göre", "carilere göre", "caride",
        "müşteri", "müşteriler", "müşteriye göre", "müşterilere göre",
        "müşteri adı", "müşteri bazında", "cari bazında", "cari hesap"
      ],
      "column": "CustomerName",
      "specificity": 1.0,
      "hint": "Cari/müşteri kolonu → group_by veya select: [CustomerName] kullan",
      "embedding_text": "Müşteri, cari hesap, müşteri adı, cari bazında, alıcı"
    },
    {
      "id": "filter_closed_table",
      "category": "status",
      "term": "ödemesi alınan masa",
      "aliases": ["kapalı masa", "tamamlanan masa", "biten masa", "ödeme alındı", "ödemesi alınan"],
      "column": "IsTableActive",
      "specificity": 1.0,
      "filter_structured": {"column": "IsTableActive", "operator": "=", "value": "0"},
      "hint": "[IsTableActive] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME",
      "embedding_text": "Kapalı masa, ödemesi tamamlanan, biten masa, ödeme alınan"
    },
    {
      "id": "filter_open_table",
      "category": "status",
      "term": "açık masa",
      "aliases": ["aktif masa", "ödemesi alınmamış masa", "masada oturan"],
      "column": "IsTableActive",
      "specificity": 1.0,
      "filter_structured": {"column": "IsTableActive", "operator": "=", "value": "1"},
      "hint": "[IsTableActive] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME",
      "embedding_text": "Açık masa, aktif masa, hâlâ masada olan, ödeme alınmamış"
    },
    {
      "id": "filter_normal_sale",
      "category": "status",
      "term": "normal satış",
      "aliases": ["standart satış", "ikram değil", "zayi değil", "iptal değil"],
      "column": "DocumentDetailIsTreatWasteCancel",
      "specificity": 0.9,
      "filter_structured": {"column": "DocumentDetailIsTreatWasteCancel", "operator": "IS NULL"},
      "hint": "[DocumentDetailIsTreatWasteCancel] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME",
      "embedding_text": "Normal satış, standart satış, ikram değil, zayi değil, iptal değil"
    },
    {
      "id": "filter_treat",
      "category": "status",
      "term": "ikram",
      "aliases": ["bedava", "ikram edilen", "ücretsiz"],
      "column": "DocumentDetailIsTreatWasteCancel",
      "specificity": 1.0,
      "filter_structured": {"column": "DocumentDetailIsTreatWasteCancel", "operator": "=", "value": "1"},
      "hint": "[DocumentDetailIsTreatWasteCancel] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME",
      "embedding_text": "İkram edilen ürün, bedava verilen, ücretsiz ürün, complimentary"
    },
    {
      "id": "filter_return",
      "category": "status",
      "term": "iade",
      "aliases": ["iade satış", "geri iade", "return"],
      "column": "DocumentTypeIsReturn",
      "specificity": 1.0,
      "filter_structured": {"column": "DocumentTypeIsReturn", "operator": "=", "value": "1"},
      "hint": "[DocumentTypeIsReturn] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME",
      "embedding_text": "İade edilen ürün, geri iade, return, iade satışı"
    },
    {
      "id": "filter_delivery",
      "category": "filter",
      "term": "paket servis",
      "aliases": ["paket", "delivery", "eve teslim", "online sipariş"],
      "column": "DocumentKindName",
      "specificity": 1.0,
      "filter_structured": {"column": "DocumentKindName", "operator": "=", "value": "Paket Servis"},
      "hint": "[DocumentKindName] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME",
      "embedding_text": "Paket servis siparişi, delivery, eve teslim, online sipariş, takeaway"
    },
    {
      "id": "filter_dine_in",
      "category": "filter",
      "term": "masa siparişi",
      "aliases": ["masada yeme", "restoran", "masa satışı"],
      "column": "DocumentKindName",
      "specificity": 1.0,
      "filter_structured": {"column": "DocumentKindName", "operator": "=", "value": "Masa"},
      "hint": "[DocumentKindName] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME",
      "embedding_text": "Masada yeme, restoran siparişi, dine in, masa satışı"
    },
    {
      "id": "filter_main_product",
      "category": "filter",
      "term": "ana ürün",
      "aliases": ["menü dışı", "bağımsız ürün", "seçenek değil"],
      "column": "MenuId",
      "specificity": 0.9,
      "filter_structured": {"column": "MenuId", "operator": "IS NULL"},
      "hint": "[MenuId] filtresi Python tarafından uygulanmaktadır — sen filters'a EKLEME",
      "embedding_text": "Ana ürün, menü dışı ürün, bağımsız ürün, menü seçeneği değil"
    }
  ]
}
```

**Step 2: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/term_dictionary.json
git commit -m "feat(term-dict): upgrade to v2.0 — add id, category, specificity, embedding_text"
```

---

### Task 2: Write failing tests for `TermVectorStore`

**Files:**
- Create: `tests/graphs/report/test_term_vector_store.py`

**Step 1: Create the test file**

```python
"""
Tests for TermVectorStore.

Core logic tested via _semantic_search() mock — no ChromaDB needed.
Focuses on conflict resolution algorithm, not embedding infrastructure.
"""
import pytest
from dataclasses import dataclass
from typing import List
from unittest.mock import MagicMock, patch


# --- Helpers to build fake TermCandidate objects ---

def _make_unambiguous(
    term_id: str,
    column: str,
    specificity: float,
    similarity: float,
    hint: str = "hint",
    filter_structured: dict = None,
    category: str = "metric",
):
    from src.graphs.report_agent.subagents.text2sql.term_vector_store import TermCandidate
    return TermCandidate(
        term_id=term_id,
        category=category,
        term=term_id,
        column=column,
        specificity=specificity,
        hint=hint,
        filter_structured=filter_structured,
        ambiguous_columns=[],
        similarity=similarity,
    )


def _make_ambiguous(
    term_id: str,
    ambiguous_columns: List[dict],
    specificity: float,
    similarity: float,
):
    from src.graphs.report_agent.subagents.text2sql.term_vector_store import TermCandidate
    return TermCandidate(
        term_id=term_id,
        category="metric",
        term=term_id,
        column="",
        specificity=specificity,
        hint="belirsiz",
        filter_structured=None,
        ambiguous_columns=ambiguous_columns,
        similarity=similarity,
    )


def _make_store_with_candidates(candidates):
    """TermVectorStore instance with mocked _semantic_search."""
    from src.graphs.report_agent.subagents.text2sql.term_vector_store import TermVectorStore
    store = TermVectorStore.__new__(TermVectorStore)
    store._semantic_search = MagicMock(return_value=candidates)
    return store


# =============================================================================
# CONFLICT RESOLUTION TESTS
# =============================================================================

class TestConflictResolution:

    def test_clear_term_ciro_no_interrupt(self):
        """
        'ciro' → RowAmount resolved. 'ne kadar sattı' ambiguous [RowAmount, Quantity]
        → RowAmount already resolved → suppress → NO interrupt.
        """
        candidates = [
            _make_unambiguous("metric_revenue", "RowAmount", specificity=1.0, similarity=0.92),
            _make_ambiguous(
                "metric_ambiguous_how_much",
                [{"column": "RowAmount", "description": "TL"}, {"column": "Quantity", "description": "Adet"}],
                specificity=0.2,
                similarity=0.71,
            ),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("ne kadar ciro yaptı")

        assert len(result.ambiguous) == 0, "ciro zaten RowAmount'ı resolve etti → interrupt olmamalı"

    def test_clear_term_ciro_hint_present(self):
        """'ciro' resolve edilince hint LLM'e iletilmeli."""
        candidates = [
            _make_unambiguous("metric_revenue", "RowAmount", specificity=1.0, similarity=0.92, hint="SUM([RowAmount]) kullan"),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("ciro")

        assert "RowAmount" in result.hints_text

    def test_ambiguous_alone_triggers_interrupt(self):
        """
        Sadece 'ne kadar sattı' match eder, başka term yok → interrupt tetiklenmeli.
        """
        candidates = [
            _make_ambiguous(
                "metric_ambiguous_how_much",
                [{"column": "RowAmount", "description": "TL"}, {"column": "Quantity", "description": "Adet"}],
                specificity=0.2,
                similarity=0.75,
            ),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("ne kadar sattı")

        assert len(result.ambiguous) == 1
        assert result.ambiguous[0].term == "metric_ambiguous_how_much"

    def test_adet_term_no_interrupt(self):
        """'kaç adet' → Quantity resolved, ambiguous suppressed."""
        candidates = [
            _make_unambiguous("metric_quantity", "Quantity", specificity=1.0, similarity=0.88),
            _make_ambiguous(
                "metric_ambiguous_how_much",
                [{"column": "RowAmount", "description": "TL"}, {"column": "Quantity", "description": "Adet"}],
                specificity=0.2,
                similarity=0.65,
            ),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("kaç adet sattı")

        assert len(result.ambiguous) == 0

    def test_filter_term_returns_term_filter(self):
        """'ikram' → filter_structured → term_filters listesine eklenmeli."""
        candidates = [
            _make_unambiguous(
                "filter_treat",
                "DocumentDetailIsTreatWasteCancel",
                specificity=1.0,
                similarity=0.90,
                category="status",
                filter_structured={"column": "DocumentDetailIsTreatWasteCancel", "operator": "=", "value": "1"},
            ),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("ikram edilen ürünler")

        assert len(result.term_filters) == 1
        assert result.term_filters[0]["column"] == "DocumentDetailIsTreatWasteCancel"
        assert result.term_filters[0]["value"] == "1"
        assert result.term_filters[0]["logical_operator"] == "AND"

    def test_below_threshold_terms_ignored(self):
        """Hiç match yoksa boş TermResolverOutput dönmeli."""
        store = _make_store_with_candidates([])

        result = store.resolve("anlamsız sorgu")

        assert result.term_filters == []
        assert result.ambiguous == []

    def test_paket_servis_and_ciro_combo(self):
        """
        'paket serviste ne kadar ciro' → filter + RowAmount hint, interrupt yok.
        """
        candidates = [
            _make_unambiguous(
                "metric_revenue", "RowAmount", specificity=1.0, similarity=0.91,
                hint="SUM([RowAmount]) kullan",
            ),
            _make_unambiguous(
                "filter_delivery", "DocumentKindName", specificity=1.0, similarity=0.87,
                category="filter",
                filter_structured={"column": "DocumentKindName", "operator": "=", "value": "Paket Servis"},
            ),
            _make_ambiguous(
                "metric_ambiguous_how_much",
                [{"column": "RowAmount", "description": "TL"}, {"column": "Quantity", "description": "Adet"}],
                specificity=0.2,
                similarity=0.68,
            ),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("paket serviste ne kadar ciro")

        assert len(result.ambiguous) == 0
        assert len(result.term_filters) == 1
        assert result.term_filters[0]["column"] == "DocumentKindName"
        assert "RowAmount" in result.hints_text

    def test_suppress_adds_hint_about_resolved_term(self):
        """
        Suppress edildiğinde hint_lines'a 'ciro ile RowAmount çözüldü' bilgisi eklenmeli.
        Bu LLM'e correct metric'i bildirir.
        """
        candidates = [
            _make_unambiguous("metric_revenue", "RowAmount", specificity=1.0, similarity=0.92, hint="SUM([RowAmount]) kullan"),
            _make_ambiguous(
                "metric_ambiguous_how_much",
                [{"column": "RowAmount", "description": "TL"}, {"column": "Quantity", "description": "Adet"}],
                specificity=0.2,
                similarity=0.71,
            ),
        ]
        store = _make_store_with_candidates(candidates)

        result = store.resolve("ne kadar ciro yaptı")

        assert "RowAmount" in result.hints_text
        assert len(result.ambiguous) == 0


# =============================================================================
# TERM RESOLVER OUTPUT STRUCTURE
# =============================================================================

class TestTermResolverOutput:

    def test_term_filters_have_logical_operator(self):
        """Her term_filter'da logical_operator='AND' olmalı."""
        candidates = [
            _make_unambiguous(
                "filter_treat", "DocumentDetailIsTreatWasteCancel", specificity=1.0, similarity=0.88,
                filter_structured={"column": "DocumentDetailIsTreatWasteCancel", "operator": "=", "value": "1"},
            ),
        ]
        store = _make_store_with_candidates(candidates)
        result = store.resolve("ikram")

        for f in result.term_filters:
            assert "logical_operator" in f

    def test_same_column_not_added_twice(self):
        """Aynı column'dan iki unambiguous match gelirse sadece biri (yüksek skoru) alınmalı."""
        candidates = [
            _make_unambiguous("metric_revenue",  "RowAmount", specificity=1.0, similarity=0.95),
            _make_unambiguous("metric_revenue_2", "RowAmount", specificity=0.8, similarity=0.80),
        ]
        store = _make_store_with_candidates(candidates)
        result = store.resolve("ciro ve tutar")

        row_amount_hints = [l for l in result.hints_text.splitlines() if "RowAmount" in l]
        assert len(row_amount_hints) == 1, "Aynı kolon için tek hint olmalı"
```

**Step 2: Run tests to verify they fail (TermVectorStore not yet created)**

```bash
pytest tests/graphs/report/test_term_vector_store.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'TermVectorStore'`

**Step 3: Commit failing tests**

```bash
git add tests/graphs/report/test_term_vector_store.py
git commit -m "test(term-vector-store): add failing tests for conflict resolution logic"
```

---

### Task 3: Create `term_vector_store.py`

**Files:**
- Create: `src/graphs/report_agent/subagents/text2sql/term_vector_store.py`

**Step 1: Create the file**

```python
"""
Term Vector Store
=================
Kullanıcı sorgusundaki Türkçe iş terimlerini semantik olarak tespit eder.

BusinessRulesVectorStore ile aynı pattern:
  - JSON → ChromaDB (sentence-transformers embedding)
  - Graph startup'ta initialize edilir
  - resolve(user_query) → TermResolverOutput

Conflict resolution algoritması:
  - Candidates sıralanır: similarity * specificity (desc)
  - Unambiguous term bir kolonu resolve ederse → resolved_columns'a eklenir
  - Ambiguous term geldiğinde: tüm kolonları zaten resolved_columns'da mı?
      Evet (tümü) → SUPPRESS, resolved term'e hint eklenir
      Kısmen     → SUPPRESS (dominant term kazanır)
      Hiçbiri    → interrupt listesine ekle

SOLID:
  S — resolve() conflict resolution, _semantic_search() ChromaDB ayrı
  O — Yeni category/term → JSON + rebuild, kod değişmez
  D — Node TermVectorStore'a depend eder, keyword logic'e değil
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_COLLECTION = "term_dictionary"
_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_SIMILARITY_THRESHOLD = 0.60
_TOP_K = 15


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class AmbiguousMatch:
    """Kullanıcıya sorulması gereken belirsiz terim."""
    term: str
    user_query: str
    options: List[Dict[str, Any]]


@dataclass
class TermResolverOutput:
    """
    TermVectorStore.resolve() dönüş tipi.

    term_filters : Python katmanı tarafından QuerySchema'ya merge edilir.
    hints_text   : LLM prompt'una inject edilir.
    ambiguous    : interrupt() ile kullanıcıya sorulacak terimler.
    """
    term_filters: List[Dict[str, Any]] = field(default_factory=list)
    hints_text: str = "Özel terim eşleşmesi bulunamadı."
    ambiguous: List[AmbiguousMatch] = field(default_factory=list)


@dataclass
class TermCandidate:
    """
    Semantic search sonucu — tek bir term entry.
    resolve() bu nesneler üzerinde çalışır.
    """
    term_id: str
    category: str
    term: str
    column: str               # "" if ambiguous
    specificity: float
    hint: str
    filter_structured: Optional[Dict[str, Any]]
    ambiguous_columns: List[Dict[str, Any]]  # [] if unambiguous
    similarity: float

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguous_columns)

    @property
    def sort_key(self) -> float:
        return self.similarity * self.specificity


# =============================================================================
# TermVectorStore
# =============================================================================

class TermVectorStore:
    """
    term_dictionary.json → ChromaDB semantic index.

    Kullanım:
        store = TermVectorStore(dict_path=..., persist_directory=...)
        store.initialize()          # graph startup'ta bir kez
        output = store.resolve(user_query)   # her sorguda
    """

    def __init__(
        self,
        dict_path: str | Path,
        persist_directory: str,
        embedding_model: str = _DEFAULT_MODEL,
        similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
    ):
        self.dict_path = Path(dict_path)
        self.similarity_threshold = similarity_threshold

        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.Client(Settings(
            persist_directory=persist_directory,
            anonymized_telemetry=False,
        ))

        import os
        try:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            from chromadb.utils import embedding_functions
            self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=embedding_model
            )
            if os.environ.get("HF_HUB_OFFLINE") == "1":
                del os.environ["HF_HUB_OFFLINE"]
        except Exception:
            os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "300"
            from chromadb.utils import embedding_functions
            self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=embedding_model
            )

        self._collection = None
        self._terms_data: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def initialize(self, force_recreate: bool = False) -> None:
        """
        Graph startup'ta çağrılır.
        Collection yoksa veya boşsa index_terms() tetikler.
        """
        if force_recreate:
            try:
                self._client.delete_collection(_DEFAULT_COLLECTION)
            except Exception:
                pass

        self._collection = self._client.get_or_create_collection(
            name=_DEFAULT_COLLECTION,
            embedding_function=self._embedding_fn,
            metadata={"description": "Turkish business term dictionary for Text-to-SQL"},
        )

        self._terms_data = self._load_dict()

        if self._collection.count() == 0:
            logger.info("[TERM_VECTOR_STORE] Collection empty, building index...")
            self.index_terms()
        else:
            logger.info(
                f"[TERM_VECTOR_STORE] Collection ready ({self._collection.count()} terms)"
            )

    def index_terms(self) -> None:
        """JSON → embed → ChromaDB. initialize() tarafından çağrılır."""
        if not self._terms_data:
            self._terms_data = self._load_dict()

        ids, documents, metadatas = [], [], []

        for entry in self._terms_data:
            term_id = entry["id"]
            embedding_text = entry.get("embedding_text") or self._build_embedding_text(entry)

            metadata = {
                "term_id":                 term_id,
                "category":                entry.get("category", ""),
                "term":                    entry["term"],
                "column":                  entry.get("column", ""),
                "specificity":             str(entry.get("specificity", 1.0)),
                "hint":                    entry.get("hint", ""),
                "filter_structured_json":  json.dumps(entry.get("filter_structured") or {}, ensure_ascii=False),
                "ambiguous_columns_json":  json.dumps(entry.get("ambiguous_columns") or [], ensure_ascii=False),
            }

            ids.append(term_id)
            documents.append(embedding_text)
            metadatas.append(metadata)

        self._collection.add(ids=ids, documents=documents, metadatas=metadatas)
        logger.info(f"[TERM_VECTOR_STORE] Indexed {len(ids)} terms")

    def resolve(self, user_query: str) -> TermResolverOutput:
        """
        Kullanıcı sorgusundaki terimleri semantik olarak tespit et.
        Conflict resolution algoritmasını uygula.
        """
        candidates = self._semantic_search(user_query)
        return self._apply_conflict_resolution(candidates, user_query)

    def rebuild_index(self) -> None:
        """Index'i sıfırdan oluştur (dict güncellenince çağır)."""
        self.initialize(force_recreate=True)

    # ------------------------------------------------------------------
    # Internal: search
    # ------------------------------------------------------------------

    def _semantic_search(self, user_query: str) -> List[TermCandidate]:
        """
        ChromaDB semantic query → List[TermCandidate].
        Ayrı metod — testlerde mock'lanabilir.
        """
        if self._collection is None:
            logger.warning("[TERM_VECTOR_STORE] Not initialized, returning empty")
            return []

        results = self._collection.query(
            query_texts=[user_query],
            n_results=min(_TOP_K, self._collection.count() or 1),
        )

        candidates: List[TermCandidate] = []
        for i, term_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i]
            similarity = 1 - distance          # cosine distance → similarity
            if similarity < self.similarity_threshold:
                continue

            meta = results["metadatas"][0][i]
            candidates.append(TermCandidate(
                term_id=term_id,
                category=meta.get("category", ""),
                term=meta.get("term", term_id),
                column=meta.get("column", ""),
                specificity=float(meta.get("specificity", "1.0")),
                hint=meta.get("hint", ""),
                filter_structured=json.loads(meta.get("filter_structured_json", "{}")) or None,
                ambiguous_columns=json.loads(meta.get("ambiguous_columns_json", "[]")),
                similarity=similarity,
            ))

        logger.debug(
            f"[TERM_VECTOR_STORE] Semantic search: {len(candidates)} candidates "
            f"(threshold={self.similarity_threshold})"
        )
        return candidates

    # ------------------------------------------------------------------
    # Internal: conflict resolution
    # ------------------------------------------------------------------

    def _apply_conflict_resolution(
        self,
        candidates: List[TermCandidate],
        user_query: str,
    ) -> TermResolverOutput:
        """
        Conflict resolution algoritması:

        1. Sort by similarity * specificity (desc) — spesifik term'ler önce işlenir
        2. Unambiguous term → resolved_columns'a ekle
        3. Ambiguous term → tüm / kısmen resolved_columns'da mı?
             Tümü → SUPPRESS
             Kısmen → SUPPRESS (dominant term kazanır)
             Hiçbiri → interrupt listesine ekle
        """
        sorted_candidates = sorted(candidates, key=lambda c: c.sort_key, reverse=True)

        resolved_columns: Dict[str, TermCandidate] = {}  # column → winning candidate
        term_filters: List[Dict[str, Any]] = []
        hint_lines: List[str] = []
        ambiguous: List[AmbiguousMatch] = []

        for candidate in sorted_candidates:

            # --- Unambiguous term ---
            if not candidate.is_ambiguous and candidate.column:
                if candidate.column not in resolved_columns:
                    resolved_columns[candidate.column] = candidate
                    hint_lines.append(f'- "{candidate.term}" → {candidate.hint}')
                    if candidate.filter_structured:
                        fs = dict(candidate.filter_structured)
                        fs.setdefault("logical_operator", "AND")
                        term_filters.append(fs)
                    logger.debug(
                        f"[TERM_VECTOR_STORE] Resolved: '{candidate.term}' → "
                        f"'{candidate.column}' (sim={candidate.similarity:.2f}, "
                        f"spec={candidate.specificity})"
                    )
                # else: same column already resolved by higher-priority term → skip
                continue

            # --- Ambiguous term ---
            if candidate.is_ambiguous:
                amb_cols = [c["column"] for c in candidate.ambiguous_columns]
                already_resolved = [c for c in amb_cols if c in resolved_columns]

                if already_resolved:
                    # SUPPRESS: at least one ambiguous column is already resolved
                    for col in already_resolved:
                        winner = resolved_columns[col]
                        hint_lines.append(
                            f'- "{candidate.term}" → "{winner.term}" terimi ile '
                            f'[{col}] olarak çözüldü (interrupt suppressed)'
                        )
                    logger.info(
                        f"[TERM_VECTOR_STORE] SUPPRESS: '{candidate.term}' ambiguity suppressed "
                        f"by {[resolved_columns[c].term for c in already_resolved]}"
                    )
                else:
                    # No column resolved → genuine ambiguity → interrupt needed
                    ambiguous.append(AmbiguousMatch(
                        term=candidate.term,
                        user_query=user_query,
                        options=candidate.ambiguous_columns,
                    ))
                    hint_lines.append(f'- "{candidate.term}" → belirsiz kolon, kullanıcıya sorulacak')
                    logger.info(
                        f"[TERM_VECTOR_STORE] AMBIGUOUS: '{candidate.term}' → "
                        f"interrupt required ({amb_cols})"
                    )

        hints_text = "\n".join(hint_lines) if hint_lines else "Özel terim eşleşmesi bulunamadı."

        logger.info(
            f"[TERM_VECTOR_STORE] resolve() done: "
            f"{len(term_filters)} filter(s), "
            f"{len([l for l in hint_lines if 'belirsiz' not in l])} hint(s), "
            f"{len(ambiguous)} interrupt(s)"
        )
        return TermResolverOutput(
            term_filters=term_filters,
            hints_text=hints_text,
            ambiguous=ambiguous,
        )

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    def _load_dict(self) -> List[Dict[str, Any]]:
        try:
            with open(self.dict_path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("terms", [])
        except Exception as e:
            logger.error(f"[TERM_VECTOR_STORE] Failed to load dict: {e}")
            return []

    @staticmethod
    def _build_embedding_text(entry: Dict[str, Any]) -> str:
        """embedding_text yoksa term + aliases birleştir."""
        parts = [entry["term"]] + entry.get("aliases", [])
        return ", ".join(parts)
```

**Step 2: Run the failing tests**

```bash
pytest tests/graphs/report/test_term_vector_store.py -v
```

Expected: All tests PASS (no ChromaDB needed — `_semantic_search` is mocked in every test).

**Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/term_vector_store.py
git commit -m "feat(term-vector-store): add TermVectorStore with semantic search + conflict resolution"
```

---

### Task 4: Update `nodes.py` — inject `TermVectorStore`

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py`

**Step 1: Replace the import at the top of nodes.py**

Find:
```python
from src.graphs.report_agent.subagents.text2sql.term_resolver import resolve_terms_structured
```

Replace with:
```python
from src.graphs.report_agent.subagents.text2sql.term_vector_store import TermVectorStore
```

**Step 2: Replace `create_term_resolver_node` function entirely**

Find the entire function (lines ~120–194) and replace:

```python
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
            "term_filters": term_filters,
            "term_hints":   hints_text,
        }

    return term_resolver_node
```

**Step 3: Run existing node-related tests to verify nothing broke**

```bash
pytest tests/graphs/report/ -v -k "not llm_integration" 2>&1 | tail -20
```

Expected: All non-integration tests pass.

**Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat(nodes): inject TermVectorStore into create_term_resolver_node"
```

---

### Task 5: Update `graph.py` — initialize `TermVectorStore` at startup

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/graph.py`

**Step 1: Replace the import block at the top**

Find:
```python
from src.graphs.report_agent.subagents.text2sql.nodes import (
    MAX_RETRY,
    create_business_rules_node,
    create_cleanup_table_node,
    create_create_table_node,
    create_schema_validator_node,
    create_sql_architect_node,
    create_sql_executor_node,
    create_sql_generator_node,
    create_term_resolver_node,
    create_value_resolver_node,
    schema_merge_node,
)
```

No change needed here — `create_term_resolver_node` is still exported from nodes.py.

Add after the existing imports:
```python
from src.graphs.report_agent.subagents.text2sql.term_vector_store import TermVectorStore
```

**Step 2: Replace the `# --- Servis başlatma ---` block inside `build_text2sql_graph`**

Find:
```python
    term_resolver       = create_term_resolver_node()
```

Replace with:
```python
    term_vector_store = TermVectorStore(
        dict_path=Path(__file__).parent / "term_dictionary.json",
        persist_directory=chroma_persist_dir,
    )
    term_vector_store.initialize()

    term_resolver       = create_term_resolver_node(term_vector_store)
```

Also add the `Path` import if not already present at top of `graph.py`:
```python
from pathlib import Path
```

**Step 3: Verify graph builds (no DB connection needed)**

```bash
python -c "
from unittest.mock import MagicMock, patch
with patch('chromadb.Client'), patch('chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction'):
    from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph
print('graph.py import OK')
"
```

Expected: `graph.py import OK`

**Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/graph.py
git commit -m "feat(graph): initialize TermVectorStore at startup, pass to term_resolver_node"
```

---

### Task 6: Delete `term_resolver.py`

**Files:**
- Delete: `src/graphs/report_agent/subagents/text2sql/term_resolver.py`

**Step 1: Verify no remaining imports**

```bash
grep -r "term_resolver" src/ --include="*.py"
```

Expected: No results (nodes.py no longer imports it after Task 4).

**Step 2: Delete the file**

```bash
git rm src/graphs/report_agent/subagents/text2sql/term_resolver.py
```

**Step 3: Run all tests**

```bash
pytest tests/graphs/report/ -v -k "not llm_integration" 2>&1 | tail -30
```

Expected: All pass.

**Step 4: Commit**

```bash
git commit -m "refactor(term-resolver): remove term_resolver.py — replaced by term_vector_store.py"
```

---

### Task 7: Run full test suite & final verification

**Step 1: Run all tests**

```bash
pytest tests/graphs/report/ -v 2>&1 | tail -40
```

**Step 2: Verify term_vector_store tests all pass**

```bash
pytest tests/graphs/report/test_term_vector_store.py -v
```

Expected: 9 tests pass.

**Step 3: Smoke test conflict resolution manually**

```bash
python -c "
from src.graphs.report_agent.subagents.text2sql.term_vector_store import TermVectorStore, TermCandidate
from unittest.mock import MagicMock

store = TermVectorStore.__new__(TermVectorStore)
store._semantic_search = MagicMock(return_value=[
    TermCandidate('metric_revenue', 'metric', 'ciro', 'RowAmount', 1.0, 'SUM RowAmount', None, [], 0.92),
    TermCandidate('metric_amb', 'metric', 'ne kadar sattı', '', 0.2, 'belirsiz', None,
                  [{'column': 'RowAmount', 'description': 'TL'}, {'column': 'Quantity', 'description': 'Adet'}], 0.71),
])

result = store.resolve('ne kadar ciro yaptı')
assert len(result.ambiguous) == 0, 'BUG: interrupt olmamalı!'
assert 'RowAmount' in result.hints_text
print('✅ Conflict resolution çalışıyor — interrupt suppressed, hint verildi')
print('hints_text:', result.hints_text)
"
```

Expected: `✅ Conflict resolution çalışıyor — interrupt suppressed, hint verildi`

**Step 4: Final commit**

```bash
git add -A
git commit -m "test(term-vector-store): verify all tests pass after full implementation"
```
