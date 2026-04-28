# ColumnResolver Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dağınık kolon normalizasyon mantığını tek, saf-Python `ColumnResolver` sınıfında topla; böylece hem entities hem metrics için Türkçe morfem soyma + semantik alias çözümleme tek noktadan, DB bağımsız, anında çalışır.

**Architecture:** `ColumnResolver` yeni bir saf-Python sınıfıdır — DB bağlantısı yok, async yok, `__init__`'te hazır. `term_resolver_node` içinde ChromaDB bulamazsa her iki tip ham metin için (entity raw_text + column_hint, metric raw_text) tek bir `ColumnResolver.resolve()` çağrısı yapılır. `schema_builder` artık fallback mantığı taşımaz: `term_resolution`'da yoksa atla. `ValueResolverService` kendi semantic map'ini bu sınıfa devreder.

**Tech Stack:** Python, rapidfuzz (opsiyonel fuzzy), pydantic, pytest

---

## Dosya Haritası

| Dosya | Değişiklik |
|---|---|
| `src/graphs/report_agent/subagents/text2sql/column_resolver.py` | **YENİ** — ColumnResolver sınıfı |
| `src/graphs/report_agent/subagents/text2sql/nodes.py` | term_resolver_node: value_resolver → column_resolver; metric döngüsü eklendi |
| `src/graphs/report_agent/subagents/text2sql/schema_builder.py` | metrics döngüsü safety net — metric.raw_text fallback kaldır |
| `src/graphs/report_agent/subagents/text2sql/value_resolver_service.py` | `_init_column_semantic_mapping()` → `__init__`'e taşı; `resolve_column_name` → ColumnResolver'a delege et |
| `src/graphs/report_agent/subagents/text2sql/graph.py` | ColumnResolver oluştur, term_resolver'a geç |
| `tests/unit/text2sql/test_column_resolver.py` | **YENİ** — ColumnResolver unit testleri |
| `tests/unit/text2sql/test_term_resolver_node_update.py` | Güncellenmiş testler (ValueResolverService mock → ColumnResolver) |
| `tests/unit/text2sql/test_schema_builder.py` | Metrics safety-net testleri |

---

### Task 1: `ColumnResolver` sınıfını oluştur

**Files:**
- Create: `src/graphs/report_agent/subagents/text2sql/column_resolver.py`
- Test: `tests/unit/text2sql/test_column_resolver.py`

**Neden:** Tüm kolon çözümleme mantığı (semantik alias, Türkçe suffix soyma, fuzzy match) tek, bağımsız, test edilebilir bir yerde. DB bağlantısı gerektirmez, `__init__`'te hazır.

- [ ] **Step 1: Test dosyasını oluştur ve ilk başarısız testleri yaz**

`tests/unit/text2sql/test_column_resolver.py` oluştur:

```python
import pytest
from src.graphs.report_agent.subagents.text2sql.column_resolver import ColumnResolver


@pytest.fixture
def resolver():
    return ColumnResolver()


# ── Doğrudan alias testi ────────────────────────────────────────────────────

def test_resolve_turkish_column_alias(resolver):
    """Türkçe semantik isim → DB kolon."""
    assert resolver.resolve("Kategori") == "CategoryName"
    assert resolver.resolve("tutar") == "RowAmount"
    assert resolver.resolve("Sube") == "BranchName"


def test_resolve_already_db_column(resolver):
    """Gerçek DB kolon adı girilince yine kendisi döner."""
    assert resolver.resolve("CategoryName") == "CategoryName"
    assert resolver.resolve("RowAmount") == "RowAmount"
    assert resolver.resolve("BranchName") == "BranchName"


def test_resolve_metric_satis(resolver):
    """'satış' metriği → RowAmount (satış normalize → satis → alias)."""
    assert resolver.resolve("satış") == "RowAmount"


def test_resolve_case_insensitive(resolver):
    """Büyük-küçük harf fark etmez."""
    assert resolver.resolve("KATEGORI") == "CategoryName"
    assert resolver.resolve("rowamount") == "RowAmount"


# ── Türkçe suffix soyma ─────────────────────────────────────────────────────

def test_strip_possessive_si(resolver):
    """'kategorisi' → strip '-si' → 'kategori' → CategoryName."""
    assert resolver.resolve("kategorisi") == "CategoryName"


def test_strip_possessive_si_with_locative(resolver):
    """'kategorisindeki' → strip '-ndeki' → 'kategorisi' → strip '-si' → CategoryName."""
    assert resolver.resolve("kategorisindeki") == "CategoryName"


def test_strip_ablative_den(resolver):
    """'şubeden' → strip '-den' → 'şube' → BranchName."""
    assert resolver.resolve("şubeden") == "BranchName"


def test_strip_locative_de(resolver):
    """'şubede' → strip '-de' → 'şube' → BranchName."""
    assert resolver.resolve("şubede") == "BranchName"


# ── column_hint fallback ────────────────────────────────────────────────────

def test_column_hint_used_when_raw_text_unknown(resolver):
    """raw_text bilinmiyorsa column_hint kullanılır."""
    assert resolver.resolve("espresso", column_hint="CategoryName") == "CategoryName"
    assert resolver.resolve("xyz123", column_hint="BranchName") == "BranchName"


def test_column_hint_ignored_when_raw_text_resolves(resolver):
    """raw_text çözülüyorsa column_hint dikkate alınmaz (doğru kolon kazanır)."""
    # 'tutar' zaten RowAmount → column_hint BranchName görmezden gelinir
    assert resolver.resolve("tutar", column_hint="BranchName") == "RowAmount"


# ── Bulunamama durumu ───────────────────────────────────────────────────────

def test_resolve_unknown_returns_none(resolver):
    """Hiçbir strateji eşleşemezse None döner."""
    assert resolver.resolve("xyzABCunknown") is None


def test_resolve_unknown_with_bad_hint_returns_none(resolver):
    """Bilinmeyen raw_text + geçersiz hint → None."""
    assert resolver.resolve("abc", column_hint="NotAColumn") is None
```

- [ ] **Step 2: Testi çalıştır — başarısız olduğunu doğrula**

```
pytest tests/unit/text2sql/test_column_resolver.py -v
```
Beklenen: `ModuleNotFoundError: No module named '...column_resolver'`

- [ ] **Step 3: `column_resolver.py`'yi oluştur**

`src/graphs/report_agent/subagents/text2sql/column_resolver.py` oluştur:

```python
"""
column_resolver.py — Saf Python kolon çözümleme katmanı.

Herhangi bir ham metin (raw_text) veya kolon ipucunu (column_hint) gerçek bir
DB kolon adına dönüştürür. DB bağlantısı yok, async yok, __init__'te hazır.

Çözümleme zinciri (sırayla):
  1. Semantik alias tablosu (normalize edilmiş eşleşme)
  2. Türkçe suffix soyma → alias tablosu
  3. column_hint (varsa) → aynı zincir
  4. Fuzzy match (db_columns biliniyorsa)
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical alias table: DB column → list of Turkish/English aliases
# Normalization (lowercase + Turkish→ASCII + no spaces/underscores) applied
# at build time so lookups are O(1).
# ---------------------------------------------------------------------------
_ALIAS_TABLE: Dict[str, List[str]] = {
    "RowAmount": [
        "tutar", "satistutar", "satistutari", "satis_tutar", "amount",
        "rowamount", "toplam", "toplamtutar", "totalamount", "revenue",
        "gelir", "ciro", "satis",
    ],
    "Quantity": ["miktar", "adet", "quantity", "qty", "sayi", "adet_miktari"],
    "DocumentDate": ["tarih", "tarihsaat", "date", "datetime", "documentdate"],
    "BranchName": ["sube", "subeadi", "sube_adi", "branch", "branchname"],
    "ProductName": ["urun", "urunadi", "urun_adi", "product", "productname", "urunlar"],
    "CategoryName": [
        "kategori", "kategoriadi", "kategori_adi", "category", "categoryname",
        "kategoriler",
    ],
    "BranchCityName": [
        "sehir", "sehiradi", "sehir_adi", "city", "cityname",
        "branchcity", "branchcityname", "il",
    ],
    "CustomerName": [
        "musteri", "musteriadi", "musteri_adi", "customer", "customername",
    ],
    "CashierName": ["kasiyer", "cashier", "cashiername"],
    "DiscountAmountTotal": [
        "indirim", "indirimtutar", "discount", "discountamounttotal",
    ],
}

# Türkçe suffix'ler — uzundan kısaya sıralı (greedy değil, ilk eşleşen alınır)
_TR_SUFFIXES: List[str] = [
    "ındaki", "indeki", "undaki", "undeki",
    "ndaki", "ndeki",
    "sından", "sinden", "sundan", "sunden",
    "ndan", "nden", "tan", "ten", "dan", "den",
    "nına", "nine", "nuna", "nune",
    "nın", "nin", "nun", "nun",
    "sına", "sine", "suna", "sune",
    "nda", "nde",
    "ta", "te", "da", "de",
    "sı", "si", "su", "sü",
    "yı", "yi", "yu", "yü",
    "ın", "in", "un", "ün",
    "ya", "ye",
    "a", "e",
]

_MIN_STEM_LEN = 3  # suffix soyulduktan sonra kalan minimum karakter


class ColumnResolver:
    """
    raw_text / column_hint → DB kolon adı çözümleyicisi.

    Kullanım::

        resolver = ColumnResolver()
        resolver.resolve("satış")            # → "RowAmount"
        resolver.resolve("kategorisi")       # → "CategoryName"
        resolver.resolve("xyz", "CategoryName")  # → "CategoryName"
    """

    def __init__(self, db_columns: Optional[List[str]] = None) -> None:
        # Normalize edilmiş alias → db_column arama tablosu
        self._lookup: Dict[str, str] = {}
        for db_col, aliases in _ALIAS_TABLE.items():
            for alias in aliases:
                self._lookup[_normalize(alias)] = db_col
            # DB kolon adının kendisi de lookup'ta olsun
            self._lookup[_normalize(db_col)] = db_col

        self._db_columns: List[str] = db_columns or []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        raw_text: str,
        column_hint: Optional[str] = None,
    ) -> Optional[str]:
        """
        raw_text (ve opsiyonel column_hint) için DB kolon adı döner.

        Zincir:
          1. normalize(raw_text) → alias tablosu
          2. strip_suffixes(raw_text) → normalize → alias tablosu
          3. normalize(column_hint) → alias tablosu  (hint varsa)
          4. fuzzy match (db_columns biliniyorsa)

        Hiçbiri başarılı olmazsa None.
        """
        # 1. Doğrudan alias
        result = self._lookup.get(_normalize(raw_text))
        if result:
            logger.debug(f"[COL_RESOLVER] '{raw_text}' → '{result}' (alias)")
            return result

        # 2. Türkçe suffix soyma
        stripped = _strip_suffixes(raw_text)
        if stripped != raw_text:
            result = self._lookup.get(_normalize(stripped))
            if result:
                logger.debug(
                    f"[COL_RESOLVER] '{raw_text}' → strip → '{stripped}' → '{result}'"
                )
                return result

        # 3. column_hint fallback
        if column_hint:
            result = self._lookup.get(_normalize(column_hint))
            if result:
                logger.debug(
                    f"[COL_RESOLVER] '{raw_text}' unknown, hint '{column_hint}' → '{result}'"
                )
                return result

        # 4. Fuzzy match (opsiyonel — db_columns inject edilmişse)
        if self._db_columns:
            try:
                from rapidfuzz import process, fuzz
                match = process.extractOne(
                    raw_text, self._db_columns, scorer=fuzz.ratio, score_cutoff=85
                )
                if match:
                    logger.debug(
                        f"[COL_RESOLVER] '{raw_text}' fuzzy → '{match[0]}' (score={match[1]})"
                    )
                    return match[0]
            except Exception:
                pass

        logger.debug(f"[COL_RESOLVER] '{raw_text}' → unresolved")
        return None

    def with_db_columns(self, columns: List[str]) -> "ColumnResolver":
        """DB kolon listesiyle fuzzy match'i etkinleştir."""
        return ColumnResolver(db_columns=columns)


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions, no state)
# ---------------------------------------------------------------------------

_TR_MAP = {
    "ı": "i", "İ": "i", "I": "i",
    "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u",
    "ş": "s", "Ş": "s",
    "ö": "o", "Ö": "o",
    "ç": "c", "Ç": "c",
}


def _normalize(text: str) -> str:
    """Küçük harf + Türkçe karakter → ASCII + boşluk/alt çizgi kaldır."""
    text = text.lower()
    for tr, en in _TR_MAP.items():
        text = text.replace(tr, en)
    return text.replace("_", "").replace(" ", "")


def _strip_suffixes(text: str) -> str:
    """
    Türkçe morfolojik suffix'leri soy.
    Kalan kök _MIN_STEM_LEN karakterden kısa olmamalı.
    """
    lower = text.lower()
    for suffix in _TR_SUFFIXES:
        if lower.endswith(suffix) and len(lower) - len(suffix) >= _MIN_STEM_LEN:
            return text[: len(text) - len(suffix)]
    return text
```

- [ ] **Step 4: Testleri çalıştır — geçtiğini doğrula**

```
pytest tests/unit/text2sql/test_column_resolver.py -v
```
Beklenen: 14 PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/column_resolver.py tests/unit/text2sql/test_column_resolver.py
git commit -m "feat(nlu): add ColumnResolver — single-source Turkish column normalization"
```

---

### Task 2: `term_resolver_node`'u `ColumnResolver` kullanacak şekilde güncelle

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:393-494`
- Modify: `src/graphs/report_agent/subagents/text2sql/graph.py:95`
- Test: `tests/unit/text2sql/test_term_resolver_node_update.py`

**Neden:** `value_resolver` bağımlılığı kaldırılır (initialization order bug'ı yok olur). Hem entity hem **metric** raw_text'leri için ColumnResolver çalıştırılır — `satış` hatası da bu adımla çözülür.

- [ ] **Step 1: Başarısız testleri yaz**

`tests/unit/text2sql/test_term_resolver_node_update.py` dosyasına mevcut testlerin ALTINA ekle:

```python
# ---------------------------------------------------------------------------
# ColumnResolver entegrasyon testleri
# ---------------------------------------------------------------------------

def _make_resolver():
    from src.graphs.report_agent.subagents.text2sql.column_resolver import ColumnResolver
    return ColumnResolver()


def test_metric_resolved_via_column_resolver():
    """
    ChromaDB metrik için eşleşme bulamazsa ColumnResolver devreye girer:
    'satış' → RowAmount.
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticIntent, SemanticMetric
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    empty = TermResolverOutput(term_filters=[], candidate_filter_terms=[], hints_text="", ambiguous=[])
    mock_store = _make_store({"satış": empty})

    node = create_term_resolver_node(mock_store, _make_resolver())
    intent = SemanticIntent(
        entities=[],
        metrics=[SemanticMetric(raw_text="satış", aggregation_hint="SUM")],
        raw_query="satış",
    )
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    assert "satış" in result["term_resolution"]
    assert result["term_resolution"]["satış"]["column_name"] == "RowAmount"


def test_entity_with_suffix_resolved_via_column_resolver():
    """
    'kategorisi' (Türkçe suffix) ChromaDB'den eşleşemezse ColumnResolver suffix soyar:
    kategorisi → kategori → CategoryName.
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity,
    )
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    empty = TermResolverOutput(term_filters=[], candidate_filter_terms=[], hints_text="", ambiguous=[])
    mock_store = _make_store({"kategorisi": empty})

    node = create_term_resolver_node(mock_store, _make_resolver())
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="kategorisi", entity_type="dimension", column_hint=None)],
        metrics=[],
        raw_query="kategorisi",
    )
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    assert "kategorisi" in result["term_resolution"]
    assert result["term_resolution"]["kategorisi"]["column_name"] == "CategoryName"


def test_column_resolver_not_called_when_chromadb_resolved():
    """ChromaDB başarılıysa ColumnResolver çağrılmaz — gereksiz iş yok."""
    from unittest.mock import patch
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticMetric,
    )
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    cft = {
        "term_id": "t_ciro",
        "term": "ciro",
        "column": "RowAmount",
        "filter_structured": None,
        "hint": "",
    }
    resolved = TermResolverOutput(
        term_filters=[], candidate_filter_terms=[cft], hints_text="", ambiguous=[],
    )
    mock_store = _make_store({"ciro": resolved})

    resolver = _make_resolver()
    with patch.object(resolver, "resolve", wraps=resolver.resolve) as mock_resolve:
        node = create_term_resolver_node(mock_store, resolver)
        intent = SemanticIntent(
            entities=[],
            metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
            raw_query="ciro",
        )
        _run(node({"semantic_intent": intent.model_dump(), "messages": []}))
        # ColumnResolver çağrılmamalı — ChromaDB zaten çözdü
        mock_resolve.assert_not_called()
```

- [ ] **Step 2: Testi çalıştır — başarısız olduğunu doğrula**

```
pytest tests/unit/text2sql/test_term_resolver_node_update.py::test_metric_resolved_via_column_resolver tests/unit/text2sql/test_term_resolver_node_update.py::test_entity_with_suffix_resolved_via_column_resolver tests/unit/text2sql/test_term_resolver_node_update.py::test_column_resolver_not_called_when_chromadb_resolved -v
```
Beklenen: FAIL (create_term_resolver_node hâlâ value_resolver alıyor)

- [ ] **Step 3: `nodes.py` — imza ve normalizasyon bloğunu güncelle**

`src/graphs/report_agent/subagents/text2sql/nodes.py` dosyasında:

**Import ekle** (dosyanın başına, mevcut importların yanına):
```python
from src.graphs.report_agent.subagents.text2sql.column_resolver import ColumnResolver
```

**`create_term_resolver_node` imzasını değiştir:**

Mevcut:
```python
def create_term_resolver_node(
    term_vector_store: TermStore,
    value_resolver: Optional[ValueResolverService] = None,
) -> Callable:
```

Yeni:
```python
def create_term_resolver_node(
    term_vector_store: TermStore,
    column_resolver: Optional[ColumnResolver] = None,
) -> Callable:
```

**Docstring'de Args bölümünü güncelle** (mevcut satırlar ~419-422):
```python
    Args:
        term_vector_store: ChromaDB-backed term resolution store.
        column_resolver:   Optional ColumnResolver. When provided and a raw_text
                           has no ChromaDB match, resolves via alias table + Turkish
                           suffix stripping. Applies to both entities and metrics.
```

**Normalizasyon bloğunu değiştir** (mevcut satırlar ~476-494):

Mevcut bloğu (if value_resolver is not None: ... for entity in intent.entities:) şununla **tamamen değiştir**:

```python
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
```

- [ ] **Step 4: `graph.py`'yi güncelle**

`src/graphs/report_agent/subagents/text2sql/graph.py` dosyasında:

**Import ekle:**
```python
from src.graphs.report_agent.subagents.text2sql.column_resolver import ColumnResolver
```

**ColumnResolver oluştur ve geç** (value_resolver ve term_store arasına ekle):

Mevcut (satır ~88-95):
```python
    term_store = TermStore(dict_path=_DATA_DIR / "term_dictionary.json")
    term_store.initialize()

    # --- Node factories ---
    ...
    term_resolver       = create_term_resolver_node(term_store, value_resolver)
```

Yeni:
```python
    term_store = TermStore(dict_path=_DATA_DIR / "term_dictionary.json")
    term_store.initialize()

    db_columns = list(column_metadata.keys()) if column_metadata else []
    column_resolver = ColumnResolver(db_columns=db_columns)

    # --- Node factories ---
    ...
    term_resolver       = create_term_resolver_node(term_store, column_resolver)
```

- [ ] **Step 5: Testleri çalıştır — geçtiğini doğrula**

```
pytest tests/unit/text2sql/test_term_resolver_node_update.py -v
```
Beklenen: Tümü PASS (eski testler de dahil — eski testlerdeki `mock_vr` artık `ColumnResolver` mock'u olmayacak, onları güncellemek gerekebilir — bak Step 6)

- [ ] **Step 6: Eski `test_term_resolver_node_update.py` testlerini güncelle**

Eski testlerde `create_term_resolver_node(mock_store, mock_vr)` çağrıları var. `mock_vr` artık `ColumnResolver` olmalı. `ColumnResolver` saf Python olduğu için gerçek instance kullanabiliriz:

`test_column_hint_normalized_when_no_term_match` testini şöyle güncelle — `mock_vr` yerine gerçek `ColumnResolver`:

```python
def test_column_hint_normalized_when_no_term_match():
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity, SemanticIntent
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput
    from src.graphs.report_agent.subagents.text2sql.column_resolver import ColumnResolver

    empty = TermResolverOutput(term_filters=[], candidate_filter_terms=[], hints_text="", ambiguous=[])
    mock_store = _make_store({"kahve": empty})

    # ColumnResolver gerçek instance — "Kategori" → "CategoryName" doğrudan
    node = create_term_resolver_node(mock_store, ColumnResolver())
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="kahve", entity_type="filter_value", column_hint="Kategori")],
        metrics=[],
        raw_query="kahve kategorisi",
    )
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    assert "kahve" in result["term_resolution"]
    assert result["term_resolution"]["kahve"]["column_name"] == "CategoryName"
```

`test_column_hint_not_called_when_term_already_resolved` — mock yerine gerçek resolver kullan (ChromaDB çözüyorsa ColumnResolver bloğuna girmez zaten):

```python
def test_column_hint_not_called_when_term_already_resolved():
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity, SemanticIntent
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput
    from src.graphs.report_agent.subagents.text2sql.column_resolver import ColumnResolver
    from unittest.mock import patch

    cft = {
        "term_id": "t1", "term": "dürüm", "column": "ProductName",
        "filter_structured": {"column": "ProductName", "operator": "=", "value": "Dürüm"},
        "hint": "",
    }
    output = TermResolverOutput(
        term_filters=[], candidate_filter_terms=[cft], hints_text="", ambiguous=[],
    )
    mock_store = _make_store({"dürüm": output})

    resolver = ColumnResolver()
    with patch.object(resolver, "resolve", wraps=resolver.resolve) as mock_resolve:
        node = create_term_resolver_node(mock_store, resolver)
        intent = SemanticIntent(
            entities=[SemanticEntity(raw_text="dürüm", entity_type="filter_value", column_hint="ProductName")],
            metrics=[],
            raw_query="dürüm",
        )
        _run(node({"semantic_intent": intent.model_dump(), "messages": []}))
        mock_resolve.assert_not_called()
```

`test_column_hint_skipped_when_resolve_column_name_returns_none` → rename + update:

```python
def test_unresolvable_entity_not_in_term_resolution():
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity, SemanticIntent
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput
    from src.graphs.report_agent.subagents.text2sql.column_resolver import ColumnResolver

    empty = TermResolverOutput(term_filters=[], candidate_filter_terms=[], hints_text="", ambiguous=[])
    mock_store = _make_store({"xyzunknown99": empty})

    node = create_term_resolver_node(mock_store, ColumnResolver())
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="xyzunknown99", entity_type="filter_value", column_hint="NotAColumn")],
        metrics=[],
        raw_query="xyzunknown99",
    )
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))
    assert "xyzunknown99" not in result["term_resolution"]
```

`test_term_resolver_node_works_without_value_resolver` → rename + update (None hâlâ desteklenmeli):

```python
def test_term_resolver_node_works_without_column_resolver():
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity, SemanticIntent
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    empty = TermResolverOutput(term_filters=[], candidate_filter_terms=[], hints_text="", ambiguous=[])
    mock_store = _make_store({"espresso": empty})
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="espresso", entity_type="filter_value", column_hint="CategoryName")],
        metrics=[],
        raw_query="espresso",
    )
    node = create_term_resolver_node(mock_store, None)
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))
    assert "term_resolution" in result
```

- [ ] **Step 7: Tüm term_resolver testlerini çalıştır**

```
pytest tests/unit/text2sql/test_term_resolver_node_update.py -v
```
Beklenen: Tümü PASS

- [ ] **Step 8: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py src/graphs/report_agent/subagents/text2sql/graph.py tests/unit/text2sql/test_term_resolver_node_update.py
git commit -m "refactor(nlu): replace value_resolver with ColumnResolver in term_resolver_node; add metric resolution"
```

---

### Task 3: `schema_builder` metrics döngüsünü düzelt

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/schema_builder.py:82-90`
- Test: `tests/unit/text2sql/test_schema_builder.py`

**Neden:** Entity döngüsünde Task 2'de (önceki plan) kaldırılan `raw_text` fallback metrics döngüsünde hâlâ var. `col = tm.column_name if tm else metric.raw_text` → `SUM([satış])` → SQL hatası. Task 2 ile term_resolution zenginleşti, bu adım güvenlik ağı.

- [ ] **Step 1: Başarısız testi yaz**

`tests/unit/text2sql/test_schema_builder.py` dosyasına ekle:

```python
def test_unresolved_metric_without_term_match_is_skipped():
    """
    term_resolution'da 'satış' yok → aggregation üretilmemeli
    (metric.raw_text kolon adı olarak kullanılmamalı).
    """
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticMetric,
    )
    intent = SemanticIntent(
        metrics=[SemanticMetric(raw_text="satış", aggregation_hint="SUM")],
        raw_query="satış",
    )
    # term_resolution'da "satış" yok
    schema = build_query_schema(intent, {}, "SINGLE", False)
    agg_columns = [a.column for a in schema.aggregations]
    assert "satış" not in agg_columns, "metric.raw_text should NEVER be used as a DB column name"
    assert len(schema.aggregations) == 0
```

- [ ] **Step 2: Testi çalıştır — başarısız olduğunu doğrula**

```
pytest tests/unit/text2sql/test_schema_builder.py::test_unresolved_metric_without_term_match_is_skipped -v
```
Beklenen: FAIL

- [ ] **Step 3: `schema_builder.py` metrics döngüsünü güncelle**

`src/graphs/report_agent/subagents/text2sql/schema_builder.py` satır 82-90'ı şununla değiştir:

Mevcut:
```python
    for metric in intent.metrics:
        tm = term_resolution.get(metric.raw_text)
        col = tm.column_name if tm else metric.raw_text
        agg = SchemaAggregation(
            function=metric.aggregation_hint,
            column=col,
            alias=_agg_alias(metric.aggregation_hint, col),
        )
        aggregations.append(agg)
```

Yeni:
```python
    for metric in intent.metrics:
        tm = term_resolution.get(metric.raw_text)
        col = tm.column_name if tm else None
        if col is None:
            logger.warning(
                f"[SCHEMA_BUILDER] No column resolved for metric '{metric.raw_text}', skipping"
            )
            continue
        agg = SchemaAggregation(
            function=metric.aggregation_hint,
            column=col,
            alias=_agg_alias(metric.aggregation_hint, col),
        )
        aggregations.append(agg)
```

- [ ] **Step 4: Tüm schema_builder testlerini çalıştır**

```
pytest tests/unit/text2sql/test_schema_builder.py -v
```
Beklenen: Tümü PASS (10 test)

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/schema_builder.py tests/unit/text2sql/test_schema_builder.py
git commit -m "fix(nlu): remove metric.raw_text-as-column fallback in schema_builder"
```

---

### Task 4: `ValueResolverService` initialization order bug'ını düzelt

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/value_resolver_service.py:18-35` (\_\_init\_\_) ve `initialize()` (satır ~200)

**Neden:** `_init_column_semantic_mapping()` şu an `initialize()` (async, DB gerekli) içinde çağrılıyor. `delta_parser.py` gibi yerlerden `resolve_column_name()` çağrıldığında DB henüz hazır olmayabilir → `column_semantic_map` boş → fuzzy match'e düşer ve `No columns available` uyarısı üretir. Semantik mapping statik Python verisidir — DB'ye bağımlılık yanlış.

- [ ] **Step 1: Testi yaz**

`tests/unit/text2sql/` altına yeni dosya oluştur: `tests/unit/text2sql/test_value_resolver_column_map.py`:

```python
"""
ValueResolverService.resolve_column_name() initialize() çağrılmadan da çalışmalı
— semantik map __init__'te hazır.
"""
from unittest.mock import MagicMock, patch


def _make_vrs():
    from src.graphs.report_agent.subagents.text2sql.value_resolver_service import ValueResolverService
    # pyodbc.connect mock — gerçek DB bağlantısı yok
    with patch("pyodbc.connect", MagicMock()):
        vrs = ValueResolverService(
            db_connection_string="mssql+pyodbc://user:pass@host/db?driver=ODBC+Driver+17+for+SQL+Server",
            table_name="TestTable",
        )
    return vrs


def test_resolve_column_name_works_before_initialize():
    """
    initialize() çağrılmadan resolve_column_name() Türkçe isimleri çözebilmeli.
    """
    vrs = _make_vrs()
    assert vrs.resolve_column_name("Kategori") == "CategoryName"
    assert vrs.resolve_column_name("tutar") == "RowAmount"
    assert vrs.resolve_column_name("Sube") == "BranchName"


def test_resolve_column_name_returns_none_for_unknown():
    vrs = _make_vrs()
    assert vrs.resolve_column_name("xyzunknown") is None
```

- [ ] **Step 2: Testi çalıştır — başarısız olduğunu doğrula**

```
pytest tests/unit/text2sql/test_value_resolver_column_map.py -v
```
Beklenen: FAIL (`resolve_column_name` henüz `column_semantic_map` boşken None döner)

- [ ] **Step 3: `ValueResolverService.__init__`'e semantic map init ekle + `resolve_column_name` güncelle**

`src/graphs/report_agent/subagents/text2sql/value_resolver_service.py` dosyasında `__init__` metodunun sonuna (satır ~34'ten sonra) şunu ekle:

```python
        # Semantic map __init__'te hazır — DB bağlantısı gerekmez
        self._init_column_semantic_mapping()
```

Ve `initialize()` içindeki aynı çağrıyı kaldır (satır ~201, `self._init_column_semantic_mapping()` satırını sil):

```python
        # 4. Semantik kolon mapping'ini hazırla  ← BU SATIRI SİL
        self._init_column_semantic_mapping()      ← BU SATIRI SİL
```

`resolve_column_name()` metodunu ColumnResolver'a delege edecek şekilde güncelle (satır ~579):

Mevcut metodun tamamını şununla değiştir:
```python
    def resolve_column_name(self, semantic_name: str) -> Optional[str]:
        """
        Semantik/doğal dil kolon adını gerçek DB kolonuna çöz.
        ColumnResolver'a delege eder — tek kaynak prensibini korur.
        """
        from src.graphs.report_agent.subagents.text2sql.column_resolver import ColumnResolver
        if not hasattr(self, "_column_resolver"):
            db_cols = list(self.column_config.keys()) if self.column_config else []
            self._column_resolver = ColumnResolver(db_columns=db_cols)
        return self._column_resolver.resolve(semantic_name)
```

- [ ] **Step 4: Testleri çalıştır**

```
pytest tests/unit/text2sql/test_value_resolver_column_map.py -v
```
Beklenen: PASS

- [ ] **Step 5: Tüm unit testleri çalıştır**

```
pytest tests/unit/text2sql/ -v
```
Beklenen: Tümü PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/value_resolver_service.py tests/unit/text2sql/test_value_resolver_column_map.py
git commit -m "fix(nlu): move semantic map init to __init__; delegate resolve_column_name to ColumnResolver"
```
