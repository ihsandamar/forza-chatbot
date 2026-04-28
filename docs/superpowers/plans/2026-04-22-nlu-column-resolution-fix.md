# NLU Column Resolution Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** İki SQL hatasını düzelt — "Incorrect syntax near 'kategorisi'" ve "Invalid column name 'Kategori'" — LLM prompt iyileştirme + term_resolver katmanında column_hint normalizasyonu + schema_builder güvenlik ağı ile derinlemesine savunma sağla.

**Architecture:** Üç katmanlı savunma. (1) LLM'i doğru raw_text ve column_hint üretmeye yönlendir; (2) term_resolver_node, LLM'in column_hint'ini ValueResolverService.resolve_column_name() ile normalize ederek sentetik TermMatch oluşturur; (3) schema_builder'da entity.raw_text → kolon fallback'i kaldırılır, bilinmeyen kolonlar atlanır (SQL hatası üretmez).

**Tech Stack:** Python, LangGraph StateGraph, Pydantic, rapidfuzz

---

## Dosya Haritası

| Dosya | Değişiklik |
|---|---|
| `src/graphs/report_agent/subagents/text2sql/prompts.py` | SEMANTIC_EXTRACTOR_PROMPT — filter_value kuralları + örnekler |
| `src/graphs/report_agent/subagents/text2sql/nodes.py` | `create_term_resolver_node` parametresi + column_hint normalization |
| `src/graphs/report_agent/subagents/text2sql/graph.py` | `create_term_resolver_node(term_store, value_resolver)` çağrısı |
| `src/graphs/report_agent/subagents/text2sql/schema_builder.py` | `entity.raw_text` → kolon fallback kaldır, None ise atla |
| `tests/unit/text2sql/test_schema_builder.py` | Yeni test: unresolved column → filter atlanır |
| `tests/unit/text2sql/test_term_resolver_node_update.py` | Yeni testler: column_hint normalization |

---

### Task 1: SEMANTIC_EXTRACTOR_PROMPT'u düzelt — raw_text ve column_hint kuralları

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/prompts.py:752-810`
- Test: `tests/unit/text2sql/test_semantic_extractor_node.py`

**Neden:** LLM bazen `raw_text="espresso kategorisi"` (Türkçe iyelik eki dahil tam öbek) + `column_hint=None` üretiyor. Bu iki hataya yol açıyor: (a) ChromaDB embedding eşleşmesi bozuluyor, (b) column_hint eksik olduğunda schema_builder fallback'i raw_text'i kolon adı olarak kullanıyor.

Düzeltme: `raw_text` sadece SAF FİLTRE DEĞERİ olmalı, Türkçe gramer yapısı hariç. `column_hint` filter_value için ZORUNLU.

- [ ] **Step 1: Başarısız testi yaz**

`tests/unit/text2sql/test_semantic_extractor_node.py` dosyasında yeni test ekle:

```python
def test_prompt_contains_filter_value_raw_text_rule():
    """SEMANTIC_EXTRACTOR_PROMPT filter_value için saf değer (ek-siz) ve zorunlu column_hint kuralını içermeli."""
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    assert "saf" in SEMANTIC_EXTRACTOR_PROMPT.lower() or "salt" in SEMANTIC_EXTRACTOR_PROMPT.lower() or "pure" in SEMANTIC_EXTRACTOR_PROMPT.lower() or "raw_text = değer" in SEMANTIC_EXTRACTOR_PROMPT.lower() or "pure değer" in SEMANTIC_EXTRACTOR_PROMPT.lower() or "filter_value için ZORUNLU" in SEMANTIC_EXTRACTOR_PROMPT


def test_prompt_contains_category_example_with_column_hint():
    """SEMANTIC_EXTRACTOR_PROMPT espresso/dürümler + CategoryName örneği içermeli."""
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    assert "CategoryName" in SEMANTIC_EXTRACTOR_PROMPT
    assert "espresso" in SEMANTIC_EXTRACTOR_PROMPT or "dürümler" in SEMANTIC_EXTRACTOR_PROMPT
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```
pytest tests/unit/text2sql/test_semantic_extractor_node.py::test_prompt_contains_filter_value_raw_text_rule tests/unit/text2sql/test_semantic_extractor_node.py::test_prompt_contains_category_example_with_column_hint -v
```
Beklenen: FAIL (ikisi de)

- [ ] **Step 3: `SEMANTIC_EXTRACTOR_PROMPT`'u güncelle**

`src/graphs/report_agent/subagents/text2sql/prompts.py` dosyasında:

**Mevcut `## entity_type KURALLARI` bölümünü şununla değiştir:**

```python
## entity_type KURALLARI

**"filter_value"**: Sorguda filtre değeri olan spesifik kavram.
  KURAL 1 — raw_text = SAF DEĞER (Türkçe gramer ekleri dahil değil):
    "espresso kategorisi" → raw_text="espresso"     (NOT "espresso kategorisi")
    "Ankara şubesi"       → raw_text="Ankara"        (NOT "Ankara şubesi")
    "dürümler kategorisi" → raw_text="dürümler"      (NOT "dürümler kategorisi")
  KURAL 2 — column_hint = filter_value için ZORUNLU, MEVCUT KOLON ADLARI listesinden seç:
    "espresso kategorisi" → entity("espresso",  filter_value, column_hint="CategoryName")
    "Ankara şubesi"       → entity("Ankara",    filter_value, column_hint="BranchName")
    "dürümler kategorisi" → entity("dürümler",  filter_value, column_hint="CategoryName")
    "son 1 yılda"         → entity DEĞİL, time alanına yaz

**"dimension"**: Gruplama boyutu. "...e göre", "...lere göre", "bazında", "kırılımı" ile gelir.
  - "ürünlere göre"     → entity("ürün",      dimension, column_hint="ProductName")
  - "kategoriler bazında" → entity("kategori", dimension, column_hint="CategoryName")

**"comparison_value"**: COMPARISON sorgusunda karşılaştırılan iki veya daha fazla spesifik değer.
  - "dürümler ve içecek karşılaştır" → entity("dürümler", comparison_value, column_hint="CategoryName") + entity("içecek", comparison_value, column_hint="CategoryName")
  - Her iki değer AYRI entity olarak yazılır
```

**Mevcut `## column_hint` bölümünü şununla değiştir:**

```python
## column_hint
- **filter_value için ZORUNLU** — MEVCUT KOLON ADLARI listesinden gerçek DB kolon adını seç.
- **dimension ve comparison_value için yaz** — biliyorsan mutlaka ekle.
- Emin değilsen MEVCUT KOLON ADLARI listesine bak; uygun kolon yoksa None bırak.
```

- [ ] **Step 4: Testi çalıştır, geçtiğini doğrula**

```
pytest tests/unit/text2sql/test_semantic_extractor_node.py::test_prompt_contains_filter_value_raw_text_rule tests/unit/text2sql/test_semantic_extractor_node.py::test_prompt_contains_category_example_with_column_hint -v
```
Beklenen: PASS

- [ ] **Step 5: Tüm semantic extractor testlerini çalıştır**

```
pytest tests/unit/text2sql/test_semantic_extractor_node.py -v
```
Beklenen: Tümü PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py tests/unit/text2sql/test_semantic_extractor_node.py
git commit -m "fix(nlu): enforce clean raw_text and mandatory column_hint in SEMANTIC_EXTRACTOR_PROMPT"
```

---

### Task 2: `term_resolver_node`'a column_hint normalizasyonu ekle

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/nodes.py:393`
- Modify: `src/graphs/report_agent/subagents/text2sql/graph.py:95`
- Test: `tests/unit/text2sql/test_term_resolver_node_update.py`

**Neden:** Task 1 sonrası LLM daha iyi column_hint üretecek, fakat mevcut ve gelecekteki kenar durumlarda (Türkçe isim "Kategori" gibi) column_hint → gerçek DB kolonu dönüşümü gerekir. `term_resolver_node`, `ValueResolverService.resolve_column_name()` ile bu normalizasyonu yaparak sentetik TermMatch ekler. Böylece schema_builder her zaman geçerli bir DB kolon adı alır.

- [ ] **Step 1: Başarısız testleri yaz**

`tests/unit/text2sql/test_term_resolver_node_update.py` dosyasına ekle:

```python
# ---------------------------------------------------------------------------
# Test: column_hint normalization via value_resolver
# ---------------------------------------------------------------------------

def test_column_hint_normalized_when_no_term_match():
    """
    Eğer ChromaDB bir raw_text için eşleşme bulamazsa ama entity'nin column_hint'i varsa,
    value_resolver.resolve_column_name(column_hint) çağrılmalı ve sonuç term_resolution'a eklenmeli.
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity, SemanticIntent
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    # ChromaDB eşleşme bulamıyor
    mock_store = _make_store({"kahve": TermResolverOutput(
        term_filters=[], candidate_filter_terms=[], hints_text="", ambiguous=[],
    )})
    mock_vr = MagicMock()
    mock_vr.resolve_column_name.return_value = "CategoryName"

    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="kahve", entity_type="filter_value", column_hint="Kategori")],
        metrics=[],
        raw_query="kahve kategorisi",
    )
    node = create_term_resolver_node(mock_store, mock_vr)
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    # resolve_column_name çağrılmalı
    mock_vr.resolve_column_name.assert_called_once_with("Kategori")
    # Sentetik TermMatch eklenmiş olmalı
    assert "kahve" in result["term_resolution"]
    assert result["term_resolution"]["kahve"]["column_name"] == "CategoryName"


def test_column_hint_not_called_when_term_already_resolved():
    """
    ChromaDB zaten eşleşme bulduysa, value_resolver.resolve_column_name çağrılmamalı.
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity, SemanticIntent
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    cft = {
        "term_id": "t1", "term": "dürüm", "column": "ProductName",
        "filter_structured": {"column": "ProductName", "operator": "=", "value": "Dürüm"},
        "hint": "",
    }
    output = TermResolverOutput(
        term_filters=[], candidate_filter_terms=[cft], hints_text="", ambiguous=[],
    )
    mock_store = _make_store({"dürüm": output})
    mock_vr = MagicMock()

    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="dürüm", entity_type="filter_value", column_hint="ProductName")],
        metrics=[],
        raw_query="dürüm",
    )
    node = create_term_resolver_node(mock_store, mock_vr)
    _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    mock_vr.resolve_column_name.assert_not_called()


def test_column_hint_skipped_when_resolve_column_name_returns_none():
    """
    resolve_column_name None dönerse, raw_text term_resolution'a eklenmemeli.
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity, SemanticIntent
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    mock_store = _make_store({"bilinmeyen": TermResolverOutput(
        term_filters=[], candidate_filter_terms=[], hints_text="", ambiguous=[],
    )})
    mock_vr = MagicMock()
    mock_vr.resolve_column_name.return_value = None  # çözülemedi

    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="bilinmeyen", entity_type="filter_value", column_hint="BilinmeyenKolon")],
        metrics=[],
        raw_query="bilinmeyen",
    )
    node = create_term_resolver_node(mock_store, mock_vr)
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    assert "bilinmeyen" not in result["term_resolution"]


def test_term_resolver_node_works_without_value_resolver():
    """
    value_resolver=None ile çağrıldığında node yine de çalışmalı (graph.py backward compat).
    """
    from src.graphs.report_agent.subagents.text2sql.nodes import create_term_resolver_node
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticEntity, SemanticIntent
    from src.graphs.report_agent.subagents.text2sql.stores.term_store import TermResolverOutput

    mock_store = _make_store({"espresso": TermResolverOutput(
        term_filters=[], candidate_filter_terms=[], hints_text="", ambiguous=[],
    )})
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="espresso", entity_type="filter_value", column_hint="CategoryName")],
        metrics=[],
        raw_query="espresso",
    )
    node = create_term_resolver_node(mock_store, None)
    result = _run(node({"semantic_intent": intent.model_dump(), "messages": []}))

    # Hata vermemeli, term_resolution boş olabilir
    assert "term_resolution" in result
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```
pytest tests/unit/text2sql/test_term_resolver_node_update.py::test_column_hint_normalized_when_no_term_match tests/unit/text2sql/test_term_resolver_node_update.py::test_column_hint_not_called_when_term_already_resolved tests/unit/text2sql/test_term_resolver_node_update.py::test_column_hint_skipped_when_resolve_column_name_returns_none tests/unit/text2sql/test_term_resolver_node_update.py::test_term_resolver_node_works_without_value_resolver -v
```
Beklenen: FAIL (`create_term_resolver_node` 2. parametre almıyor)

- [ ] **Step 3: `nodes.py` — `create_term_resolver_node` imzasını ve gövdesini güncelle**

`src/graphs/report_agent/subagents/text2sql/nodes.py` dosyasında:

**Mevcut:**
```python
def create_term_resolver_node(term_vector_store: TermStore) -> Callable:
```
**Yeni:**
```python
def create_term_resolver_node(
    term_vector_store: TermStore,
    value_resolver: Optional[ValueResolverService] = None,
) -> Callable:
```

`term_resolver_node` içinde, `term_resolution` dict'i doldurulduktan **hemen sonra**, `return {` satırından **önce** şu bloğu ekle:

```python
            # Column-hint normalization for unresolved entities
            # When ChromaDB has no match but entity has column_hint,
            # normalize hint to real DB column via ValueResolverService.
            if value_resolver is not None:
                for entity in intent.entities:
                    if entity.raw_text not in term_resolution and entity.column_hint:
                        resolved_col = value_resolver.resolve_column_name(entity.column_hint)
                        if resolved_col:
                            term_resolution[entity.raw_text] = {
                                "column_name": resolved_col,
                                "filter_structured": None,
                                "specificity": 0.5,
                                "similarity": 0.0,
                            }
                            logger.info(
                                f"[TERM_RESOLVER] column_hint fallback: '{entity.raw_text}' "
                                f"→ '{resolved_col}' (hint='{entity.column_hint}')"
                            )
```

Kesin yer: `term_resolver_node` içinde `logger.info(f"[TERM_RESOLVER] semantic_intent path: ..."` satırından hemen önce.

- [ ] **Step 4: `graph.py` — `value_resolver`'ı geç**

`src/graphs/report_agent/subagents/text2sql/graph.py` dosyasında:

**Mevcut:**
```python
    term_resolver       = create_term_resolver_node(term_store)
```
**Yeni:**
```python
    term_resolver       = create_term_resolver_node(term_store, value_resolver)
```

- [ ] **Step 5: Testleri çalıştır, geçtiğini doğrula**

```
pytest tests/unit/text2sql/test_term_resolver_node_update.py -v
```
Beklenen: Tümü PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py src/graphs/report_agent/subagents/text2sql/graph.py tests/unit/text2sql/test_term_resolver_node_update.py
git commit -m "fix(nlu): normalize column_hint via ValueResolverService in term_resolver_node"
```

---

### Task 3: `schema_builder`'dan `entity.raw_text` kolon fallback'ini kaldır

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/schema_builder.py:96-112`
- Test: `tests/unit/text2sql/test_schema_builder.py`

**Neden:** Son savunma katmanı. Task 1 ve 2 sonrasında bu kod satırına sıfır hatalı input gelmesi beklenir; ancak gelirse `entity.raw_text`'i kolon adı olarak SQL'e göndermek yerine entity'yi atlamak SQL hatasından çok daha iyidir.

- [ ] **Step 1: Başarısız testi yaz**

`tests/unit/text2sql/test_schema_builder.py` dosyasına ekle:

```python
def test_unresolved_filter_value_without_column_hint_is_skipped():
    """
    term_resolution'da eşleşme yok ve column_hint=None ise,
    filter_value entity'si için SchemaFilter üretilmemeli (raw_text kolon adı olarak kullanılmamalı).
    """
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    intent = SemanticIntent(
        entities=[
            SemanticEntity(raw_text="espresso kategorisi", entity_type="filter_value", column_hint=None),
        ],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="espresso kategorisi ciro",
    )
    # term_resolution'da "espresso kategorisi" yok (ChromaDB bulamadı, column_hint normalization da yapılamadı)
    term_resolution = {"ciro": _make_tm("RowAmount")}
    schema = build_query_schema(intent, term_resolution, "SINGLE", False)

    # "espresso kategorisi" kolon adlı bir filter OLMAMALI
    column_names = [f.column for f in schema.filters if f.column != "DocumentDate"]
    assert "espresso kategorisi" not in column_names, (
        "entity.raw_text should NEVER be used as a DB column name"
    )


def test_unresolved_dimension_without_column_hint_is_skipped():
    """
    term_resolution'da eşleşme yok ve column_hint=None ise,
    dimension entity'si group_by'a eklenmemeli.
    """
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    intent = SemanticIntent(
        entities=[
            SemanticEntity(raw_text="bilinmeyen boyut", entity_type="dimension", column_hint=None),
        ],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="bilinmeyen boyut ciro",
    )
    term_resolution = {"ciro": _make_tm("RowAmount")}
    schema = build_query_schema(intent, term_resolution, "LISTING", False)

    assert "bilinmeyen boyut" not in schema.group_by
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu doğrula**

```
pytest tests/unit/text2sql/test_schema_builder.py::test_unresolved_filter_value_without_column_hint_is_skipped tests/unit/text2sql/test_schema_builder.py::test_unresolved_dimension_without_column_hint_is_skipped -v
```
Beklenen: FAIL (mevcut kod raw_text'i kolon olarak kullanıyor)

- [ ] **Step 3: `schema_builder.py` entity döngüsünü güncelle**

`src/graphs/report_agent/subagents/text2sql/schema_builder.py` dosyasında `build_query_schema` içindeki entity for döngüsünü güncelle.

**Mevcut (satır 96-112):**
```python
    for entity in intent.entities:
        tm = term_resolution.get(entity.raw_text)
        col = (tm.column_name if tm else None) or entity.column_hint or entity.raw_text

        if entity.entity_type == "dimension":
            # Dimension → GROUP BY
            if col not in group_by:
                group_by.append(col)

        elif entity.entity_type == "comparison_value":
            # Accumulate for single IN filter per column
            comparison_groups[col].append(entity.raw_text)

        elif entity.entity_type == "filter_value":
            # Regular filter — may be pre-built (filter_structured) or simple equality
            sf = _build_filter_from_entity(entity.raw_text, col, tm)
            filters.append(sf)
```

**Yeni:**
```python
    for entity in intent.entities:
        tm = term_resolution.get(entity.raw_text)
        col = (tm.column_name if tm else None) or entity.column_hint
        if col is None:
            logger.warning(
                f"[SCHEMA_BUILDER] No column resolved for '{entity.raw_text}' "
                f"(entity_type={entity.entity_type}), skipping"
            )
            continue

        if entity.entity_type == "dimension":
            # Dimension → GROUP BY
            if col not in group_by:
                group_by.append(col)

        elif entity.entity_type == "comparison_value":
            # Accumulate for single IN filter per column
            comparison_groups[col].append(entity.raw_text)

        elif entity.entity_type == "filter_value":
            # Regular filter — may be pre-built (filter_structured) or simple equality
            sf = _build_filter_from_entity(entity.raw_text, col, tm)
            filters.append(sf)
```

- [ ] **Step 4: Testleri çalıştır, geçtiğini doğrula**

```
pytest tests/unit/text2sql/test_schema_builder.py -v
```
Beklenen: Tümü PASS

- [ ] **Step 5: Tüm unit testlerini çalıştır**

```
pytest tests/unit/text2sql/ -v
```
Beklenen: Tümü PASS

- [ ] **Step 6: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/schema_builder.py tests/unit/text2sql/test_schema_builder.py
git commit -m "fix(nlu): remove entity.raw_text-as-column fallback in schema_builder, skip unresolved entities safely"
```
