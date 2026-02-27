# Term Vector Store — Design Document

**Date:** 2026-02-27
**Status:** Approved

---

## Problem

`term_resolver.py` deterministik keyword/fuzzy matching kullanıyor.
"Son 1 senede en çok hangi ürün ne kadar ciro yaptı" sorgusunda:

- `"ciro"` → substring exact match → RowAmount (doğru)
- `"ne kadar"` (alias of `"ne kadar sattı"`) → substring match → ambiguous interrupt (yanlış)

"Ciro" terimi RowAmount'ı zaten resolve etmiş olsa bile `"ne kadar sattı"` için
interrupt tetikleniyor. Sistem anlam görmüyor, kelime yakalıyor.

---

## Solution: TermVectorStore (Approach B)

`BusinessRulesVectorStore` ile aynı pattern:

- JSON → ChromaDB → semantic embedding
- Sorgu zamanında kelime eşleştirme yerine vektör benzerliği
- Specificity-based conflict resolution: spesifik term ambiguous'u suppress eder
- Graph startup'ta initialize edilir

---

## JSON Structure v2.0

```json
{
  "version": "2.0",
  "terms": [
    {
      "id": "metric_revenue",
      "category": "metric",
      "term": "ciro",
      "aliases": ["satış tutarı", "gelir", "revenue", "tutar", "hasılat", "kazanç"],
      "column": "RowAmount",
      "specificity": 1.0,
      "hint": "Satış tutarını temsil eder → SUM([RowAmount]) kullan",
      "embedding_text": "Ciro, gelir, hasılat, satış tutarı, para birimi cinsinden satış değeri"
    },
    {
      "id": "metric_ambiguous_how_much",
      "category": "metric",
      "term": "ne kadar sattı",
      "aliases": ["ne kadar", "ne kadar satıldı", "ne kadar oldu", "toplam satış"],
      "specificity": 0.2,
      "ambiguous_columns": [
        {"column": "RowAmount", "description": "Satış tutarı (TL)"},
        {"column": "Quantity",  "description": "Satış miktarı (Adet)"}
      ],
      "embedding_text": "Satış miktarı veya tutarı belirsiz soru"
    }
  ]
}
```

### `category` alanı (extensibility)

| Değer       | Kullanım                                            |
|-------------|-----------------------------------------------------|
| `metric`    | Aggregation target — SUM/COUNT kolonu               |
| `dimension` | GROUP BY / SELECT kolonu (ProductName, BranchName)  |
| `filter`    | WHERE filtresi (IsTableActive, DocumentKindName)    |
| `status`    | Enum filtresi (ikram, iade, normal satış)           |

### Yeni alanlar

| Alan             | Tip    | Açıklama                                                  |
|------------------|--------|-----------------------------------------------------------|
| `id`             | str    | Unique identifier (ChromaDB doc ID)                       |
| `category`       | str    | Gelecek genişleme için semantik kategori                  |
| `specificity`    | float  | 0.0–1.0: ne kadar spesifik/unambiguous                   |
| `embedding_text` | str?   | Custom embed metni. Yoksa: `term + aliases` kullanılır    |

---

## Architecture

### Dosya Değişiklikleri

```
text2sql/
├── term_dictionary.json       ← v2.0 (güncellenir)
├── term_vector_store.py       ← YENİ — TermVectorStore sınıfı
├── term_resolver.py           ← SİLİNİR (temiz mimari)
├── nodes.py                   ← create_term_resolver_node(term_vector_store) alır
└── graph.py                   ← TermVectorStore initialize edilir
```

### TermVectorStore Public API

```python
class TermVectorStore:
    def __init__(
        self,
        dict_path: str | Path,
        persist_directory: str,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        similarity_threshold: float = 0.60,
    ): ...

    def initialize(self, force_recreate: bool = False) -> None:
        """Graph startup'ta çağrılır. Collection boşsa index_terms() tetikler."""

    def index_terms(self) -> None:
        """JSON → embed → ChromaDB."""

    def resolve(self, user_query: str) -> TermResolverOutput:
        """Semantic search + conflict resolution → term_filters, term_hints, ambiguous."""
```

### `resolve()` Algoritması

```
1. ChromaDB semantic query (top_k=15, min_similarity=0.60)
2. Sort by: similarity * specificity (desc)

resolved_columns: dict[str, TermEntry] = {}
term_filters = []
hints = []
ambiguous = []

for candidate in sorted_candidates:

    # Unambiguous term
    if candidate.column:
        if column not in resolved_columns:
            resolved_columns[column] = candidate
            hints.append(candidate.hint)
            if candidate.filter_structured:
                term_filters.append(candidate.filter_structured)

    # Ambiguous term
    if candidate.ambiguous_columns:
        unresolved = [c for c in amb_cols if c["column"] not in resolved_columns]

        if not unresolved:
            # SUPPRESS — tüm kolonlar zaten resolve edilmiş
            # En yüksek specificity term'e "seçildi" bilgisi hint olarak eklendi
            continue

        if len(unresolved) == len(amb_cols):
            # Hiçbiri resolve edilmemiş → interrupt gerekli
            ambiguous.append(AmbiguousMatch(...))
        else:
            # Kısmen resolve → suppress (dominant term kazanır)
            continue

3. Return TermResolverOutput(term_filters, hints_text, ambiguous)
```

### Graph Initialization (graph.py)

```python
term_vector_store = TermVectorStore(
    dict_path=Path(__file__).parent / "term_dictionary.json",
    persist_directory=chroma_persist_dir,   # mevcut chroma_db paylaşılır
)
term_vector_store.initialize()

term_resolver = create_term_resolver_node(term_vector_store)
```

### Node Signature (nodes.py)

```python
# ÖNCE
def create_term_resolver_node() -> Callable: ...

# SONRA
def create_term_resolver_node(term_vector_store: TermVectorStore) -> Callable: ...
```

Node sadece state okuma/yazma yapar. Resolution logic tamamen `TermVectorStore`'da (SRP).

---

## Conflict Resolution Örneği

**Query:** "Son 1 senede en çok hangi ürün ne kadar ciro yaptı"

```
Semantic matches:
  "ciro"           similarity=0.92  specificity=1.0  → RowAmount (unambiguous)
  "adet"           similarity=0.43  < threshold      → SKIP
  "ne kadar sattı" similarity=0.71  specificity=0.2  → ambiguous [RowAmount, Quantity]

Conflict resolution:
  "ciro" (score=0.92) processes first
  resolved_columns = {"RowAmount": "ciro_entry"}

  "ne kadar sattı" processes next
  unresolved = [c for c in [RowAmount, Quantity] if c not in resolved_columns]
             = [Quantity]  ← RowAmount resolved!
  len(unresolved) != len(amb_cols)  → SUPPRESS (partial resolution = dominant wins)

Result:
  term_filters = []
  term_hints   = '- "ciro" → SUM([RowAmount]) kullan'
  ambiguous    = []   ← INTERRUPT YOK ✅
```

---

## SOLID Uyumu

| Prensip | Nasıl |
|---------|-------|
| **S** — SRP | `TermVectorStore` sadece resolution; node sadece state I/O |
| **O** — OCP | Yeni category/term JSON + rebuild ile eklenir, kod değişmez |
| **L** — LSP | `TermResolverOutput` aynı interface, node kodu değişmez |
| **I** — ISP | `resolve()` tek entry point, node fazla metod bilmiyor |
| **D** — DIP | Node `TermVectorStore`'a depend eder, concrete keyword logic'e değil |

---

## Test Senaryoları

| Query | Beklenen |
|-------|----------|
| "ne kadar ciro yaptı" | interrupt YOK, RowAmount hint |
| "kaç adet sattı" | interrupt YOK, Quantity hint |
| "ne kadar sattı" (tek başına) | interrupt: RowAmount / Quantity |
| "ikram edilen ürünler" | filter: DocumentDetailIsTreatWasteCancel=1 |
| "paket serviste ne kadar ciro" | RowAmount + DocumentKindName filter, interrupt yok |
