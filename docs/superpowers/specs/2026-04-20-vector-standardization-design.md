# Vector Store Standardization Design

**Date:** 2026-04-20  
**Status:** Approved  
**Scope:** `src/factories/`, `src/graphs/report_agent/`

---

## Problem

Üç ayrı vector store sistemi tutarsız şekilde organize edilmiş:

1. `routing/graph.py` — OpenAI Embeddings + LangChain Chroma (persistent)
2. `text2sql/business_rules_vector_store.py` — SentenceTransformer + raw ChromaDB (in-memory)
3. `text2sql/term_vector_store.py` — SentenceTransformer + raw ChromaDB (in-memory)

Sorunlar:
- `report_agent/business_rules_vector_store.py` — `subagents/text2sql/` altındakinin eski kopyası, sadece `preload_embedding_model` için `api/main.py`'de kullanılıyor
- `BusinessRulesVectorStore` ve `TermVectorStore` aynı SentenceTransformer başlatma kodunu (offline-first pattern) copy-paste etmiş
- Initialization API tutarsız: biri `initialize_collections()` + `index_rules()` ayrı, diğeri `initialize()` tek metod
- Data dosyaları dağınık: `business_rules.json` → `data/`, `term_dictionary.json` → `subagents/text2sql/`

---

## Hedef

- Her dosyanın amacı konumundan ve adından okunabilir olsun
- Embedding oluşturma tek yerden yönetilsin (`EmbeddingFactory`)
- Vector store'lar ortak bir `BaseVectorStore`'dan türesin
- Data dosyaları tek klasörde kategorize edilsin
- Backend'ler değişmez: routing OpenAI'da, text2sql SentenceTransformer'da kalır

---

## Klasör Yapısı

```
src/
  factories/
    llm_factory.py                      (mevcut — değişmez)
    embedding_factory.py                ← YENİ

  graphs/
    report_agent/
      data/
        vector/                         ← YENİ klasör
          business_rules.json           (data/'dan taşınır)
          term_dictionary.json          (subagents/text2sql/'dan taşınır)

      business_rules_vector_store.py    ← SİLİNİR (eski duplicate)

      subagents/text2sql/
        stores/                         ← YENİ klasör
          __init__.py
          base.py                       ← BaseVectorStore
          business_rules_store.py       (business_rules_vector_store.py → refactor)
          term_store.py                 (term_vector_store.py → refactor)

        business_rules_vector_store.py  ← SİLİNİR
        term_vector_store.py            ← SİLİNİR
```

---

## EmbeddingFactory

**Dosya:** `src/factories/embedding_factory.py`

Şu an her store'da copy-paste olan offline-first SentenceTransformer pattern'ı tek yerde toplanır. `preload_embedding_model()` fonksiyonu da buraya taşınır.

```python
class EmbeddingFactory:
    @staticmethod
    def create_sentence_transformer(
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> SentenceTransformerEmbeddingFunction:
        """
        HF_HUB_OFFLINE=1 ile offline-first dener, başarısız olursa
        HF_HUB_DOWNLOAD_TIMEOUT=300 ile online fallback yapar.
        """
        ...

    @staticmethod
    def create_openai(
        model: str,
        api_key: str,
        base_url: str | None = None,
    ) -> OpenAIEmbeddings:
        """routing/graph.py için OpenAI embeddings."""
        ...


def preload_embedding_model(
    model: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> bool:
    """
    api/main.py startup'ta çağrılır.
    Model cache'e indirilmezse ChromaDB ilk sorguda yavaş olur.
    """
    ...
```

---

## BaseVectorStore

**Dosya:** `src/graphs/report_agent/subagents/text2sql/stores/base.py`

`BusinessRulesStore` iki collection (`business_rules` + `default_business_rules`) kullanırken `TermStore` tek collection kullanır. Bu nedenle BaseVectorStore collection yönetimini her store'a bırakır; ortak altyapıyı (ChromaDB client, embedding function, rebuild API) sağlar.

```python
class BaseVectorStore(ABC):
    def __init__(self, embedding_fn):
        self._client = chromadb.EphemeralClient()
        self._embedding_fn = embedding_fn

    @abstractmethod
    def initialize(self, force_recreate: bool = False) -> None:
        """Collection(lar)ı oluştur ve index'i hazırla."""

    def rebuild(self) -> None:
        """Index'i sıfırdan oluştur."""
        self.initialize(force_recreate=True)
```

Her store `initialize()` içinde kendi collection(lar)ını oluşturur ve `_build_index()` / `index_terms()` metodlarını çağırır.

---

## BusinessRulesStore

**Dosya:** `src/graphs/report_agent/subagents/text2sql/stores/business_rules_store.py`

Mevcut `BusinessRulesVectorStore`'un refactor edilmiş hali. Değişenler:
- `BaseVectorStore`'dan miras alır
- Constructor: `EmbeddingFactory.create_sentence_transformer()` kullanır
- `initialize_collections()` + `index_rules()` → `initialize()` (base'den gelir)
- `_build_index()` implement eder (eski `index_rules()` mantığı)
- Kendi search/resolve/cache mantığı korunur

---

## TermStore

**Dosya:** `src/graphs/report_agent/subagents/text2sql/stores/term_store.py`

Mevcut `TermVectorStore`'un refactor edilmiş hali. Değişenler:
- `BaseVectorStore`'dan miras alır
- Constructor: `EmbeddingFactory.create_sentence_transformer()` kullanır
- `initialize()` base'den gelir; `index_terms()` → `_build_index()` olarak rename edilir
- Keyword pre-resolve, semantic search, conflict resolution korunur

---

## Etkilenen Dosyalar

| Dosya | Değişim |
|---|---|
| `src/factories/embedding_factory.py` | YENİ |
| `stores/__init__.py` | YENİ |
| `stores/base.py` | YENİ |
| `stores/business_rules_store.py` | YENİ (eski refactor) |
| `stores/term_store.py` | YENİ (eski refactor) |
| `data/vector/business_rules.json` | TAŞINDI |
| `data/vector/term_dictionary.json` | TAŞINDI |
| `text2sql/graph.py` | import path + data path güncelleme |
| `routing/graph.py` | `EmbeddingFactory.create_openai()` kullanır |
| `api/main.py` | `preload_embedding_model` import kaynağı değişir |
| `report_agent/configuration.py` | `business_rules_path` default path güncellenir |
| `report_agent/graph.py` | `business_rules_path` default path güncellenir |
| `report_agent/business_rules_vector_store.py` | SİLİNİR |
| `text2sql/business_rules_vector_store.py` | SİLİNİR |
| `text2sql/term_vector_store.py` | SİLİNİR |

---

## Değişmeyen Şeyler

- Embedding backend'leri: routing OpenAI'da, text2sql SentenceTransformer'da kalır
- `BusinessRulesStore` ve `TermStore`'un iş mantığı (search, resolve, cache, conflict resolution) değişmez
- `routing/graph.py`'deki LangChain Chroma persistent store mantığı değişmez — sadece embedding oluşturma satırı factory'ye geçer
- Public API: graph.py'deki node factory fonksiyonları aynı signature'ı korur
