# Vector Store Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate tüm vector store altyapısını — paylaşımlı `EmbeddingFactory`, ortak `BaseVectorStore`, standart `stores/` klasörü ve merkezi `data/vector/` — ile tutarlı, okunabilir bir yapıya taşı.

**Architecture:** `EmbeddingFactory` (src/factories/) SentenceTransformer ve OpenAI embedding oluşturmayı tek yerden yönetir. `BaseVectorStore` (stores/base.py) ChromaDB client ve `rebuild()` API'sini sağlar; her store `initialize()` + `_build_index()` implement eder. Tüm JSON data dosyaları `data/vector/` altında toplanır.

**Tech Stack:** chromadb 1.3.4, sentence-transformers 5.2.0, langchain-chroma 1.0.0, langchain-openai, pytest, unittest.mock

---

## File Map

| Dosya | Eylem |
|---|---|
| `src/factories/embedding_factory.py` | YENİ |
| `src/graphs/report_agent/subagents/text2sql/stores/__init__.py` | YENİ |
| `src/graphs/report_agent/subagents/text2sql/stores/base.py` | YENİ |
| `src/graphs/report_agent/subagents/text2sql/stores/business_rules_store.py` | YENİ (eski refactor) |
| `src/graphs/report_agent/subagents/text2sql/stores/term_store.py` | YENİ (eski refactor) |
| `src/graphs/report_agent/data/vector/business_rules.json` | TAŞINDI |
| `src/graphs/report_agent/data/vector/term_dictionary.json` | TAŞINDI |
| `src/graphs/report_agent/subagents/text2sql/graph.py` | GÜNCELLENDI |
| `src/graphs/report_agent/graph.py` | GÜNCELLENDI |
| `src/graphs/report_agent/configuration.py` | GÜNCELLENDI |
| `src/graphs/routing/graph.py` | GÜNCELLENDI |
| `src/api/main.py` | GÜNCELLENDI |
| `tests/unit/test_embedding_factory.py` | YENİ |
| `tests/unit/test_base_vector_store.py` | YENİ |
| `tests/test_business_rules_cache.py` | GÜNCELLENDI (import path) |
| `tests/unit/test_vectorstore_auto_init.py` | GÜNCELLENDI (patch target) |
| `src/graphs/report_agent/business_rules_vector_store.py` | SİLİNDİ |
| `src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py` | SİLİNDİ |
| `src/graphs/report_agent/subagents/text2sql/term_vector_store.py` | SİLİNDİ |

---

## Task 1: EmbeddingFactory

**Files:**
- Create: `src/factories/embedding_factory.py`
- Create: `tests/unit/test_embedding_factory.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_embedding_factory.py
from unittest.mock import MagicMock, patch
import pytest


def test_create_sentence_transformer_returns_embedding_fn():
    mock_fn = MagicMock()
    with patch("src.factories.embedding_factory.embedding_functions") as mock_ef:
        mock_ef.SentenceTransformerEmbeddingFunction.return_value = mock_fn
        from src.factories.embedding_factory import EmbeddingFactory
        result = EmbeddingFactory.create_sentence_transformer("test-model")
    assert result is mock_fn
    mock_ef.SentenceTransformerEmbeddingFunction.assert_called_once_with(model_name="test-model")


def test_create_sentence_transformer_uses_default_model():
    with patch("src.factories.embedding_factory.embedding_functions") as mock_ef:
        mock_ef.SentenceTransformerEmbeddingFunction.return_value = MagicMock()
        from src.factories.embedding_factory import EmbeddingFactory
        EmbeddingFactory.create_sentence_transformer()
    call_kwargs = mock_ef.SentenceTransformerEmbeddingFunction.call_args[1]
    assert "all-MiniLM-L6-v2" in call_kwargs["model_name"]


def test_create_openai_passes_correct_args():
    mock_embeddings = MagicMock()
    with patch("src.factories.embedding_factory.OpenAIEmbeddings", return_value=mock_embeddings) as mock_cls:
        from src.factories.embedding_factory import EmbeddingFactory
        result = EmbeddingFactory.create_openai("text-embedding-3-large", "sk-test", "https://api.openai.com/v1")
    assert result is mock_embeddings
    mock_cls.assert_called_once_with(
        model="text-embedding-3-large",
        openai_api_key="sk-test",
        base_url="https://api.openai.com/v1",
    )


def test_create_openai_accepts_none_base_url():
    with patch("src.factories.embedding_factory.OpenAIEmbeddings") as mock_cls:
        from src.factories.embedding_factory import EmbeddingFactory
        EmbeddingFactory.create_openai("model", "key", None)
    mock_cls.assert_called_once_with(model="model", openai_api_key="key", base_url=None)


def test_preload_embedding_model_returns_true_on_success():
    with patch("src.factories.embedding_factory.SentenceTransformer"):
        from src.factories.embedding_factory import preload_embedding_model
        assert preload_embedding_model("test-model") is True


def test_preload_embedding_model_returns_false_on_failure():
    with patch("src.factories.embedding_factory.SentenceTransformer", side_effect=Exception("no model")):
        from src.factories.embedding_factory import preload_embedding_model
        assert preload_embedding_model("test-model") is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_embedding_factory.py -v
```
Expected: `ModuleNotFoundError` veya `ImportError` — dosya henüz yok.

- [ ] **Step 3: Create EmbeddingFactory**

```python
# src/factories/embedding_factory.py
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_ST_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def preload_embedding_model(model: str = _DEFAULT_ST_MODEL) -> bool:
    """
    Download and cache the SentenceTransformer model at startup.
    Called once by api/main.py so first-query latency is not affected.
    """
    try:
        from sentence_transformers import SentenceTransformer

        os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "300"
        SentenceTransformer(model)
        logger.info(f"[EMBEDDING] Model loaded: {model}")
        return True
    except Exception as e:
        logger.error(f"[EMBEDDING] Failed to preload model: {e}")
        logger.warning("[EMBEDDING] First-query latency may be higher")
        return False


class EmbeddingFactory:
    @staticmethod
    def create_sentence_transformer(
        model: str = _DEFAULT_ST_MODEL,
    ):
        """
        Return a ChromaDB-compatible SentenceTransformer embedding function.
        Tries offline cache first; falls back to online download with 5-min timeout.
        """
        from chromadb.utils import embedding_functions

        try:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model)
            if os.environ.get("HF_HUB_OFFLINE") == "1":
                del os.environ["HF_HUB_OFFLINE"]
            return fn
        except Exception as e:
            logger.warning(f"[EMBEDDING] Offline load failed: {e} — trying online...")
            os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "300"
            return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model)

    @staticmethod
    def create_openai(
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
    ):
        """Return a LangChain OpenAIEmbeddings instance for the routing graph."""
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=model,
            openai_api_key=api_key,
            base_url=base_url,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit/test_embedding_factory.py -v
```
Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/factories/embedding_factory.py tests/unit/test_embedding_factory.py
git commit -m "feat: add EmbeddingFactory with SentenceTransformer + OpenAI backends"
```

---

## Task 2: BaseVectorStore

**Files:**
- Create: `src/graphs/report_agent/subagents/text2sql/stores/base.py`
- Create: `tests/unit/test_base_vector_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_base_vector_store.py
from unittest.mock import MagicMock, patch
import pytest


class ConcreteStore:
    """Minimal concrete subclass for testing BaseVectorStore."""
    def __init__(self, embedding_fn):
        from src.graphs.report_agent.subagents.text2sql.stores.base import BaseVectorStore
        # Patch chromadb so no real client is created
        with patch("src.graphs.report_agent.subagents.text2sql.stores.base.chromadb"):
            # Can't instantiate ABC directly, use __new__ trick
            pass

    @staticmethod
    def make(embedding_fn=None):
        with patch("src.graphs.report_agent.subagents.text2sql.stores.base.chromadb"):
            from src.graphs.report_agent.subagents.text2sql.stores.base import BaseVectorStore

            class Impl(BaseVectorStore):
                def __init__(self):
                    super().__init__(embedding_fn or MagicMock())
                    self.init_calls = []

                def initialize(self, force_recreate: bool = False) -> None:
                    self.init_calls.append(force_recreate)

            return Impl()


def test_rebuild_calls_initialize_with_force_recreate_true():
    store = ConcreteStore.make()
    store.rebuild()
    assert store.init_calls == [True]


def test_embedding_fn_stored_on_instance():
    mock_fn = MagicMock()
    store = ConcreteStore.make(mock_fn)
    assert store._embedding_fn is mock_fn


def test_client_created_on_init():
    with patch("src.graphs.report_agent.subagents.text2sql.stores.base.chromadb") as mock_chroma:
        from src.graphs.report_agent.subagents.text2sql.stores.base import BaseVectorStore

        class Impl(BaseVectorStore):
            def initialize(self, force_recreate=False):
                pass

        Impl(MagicMock())
        mock_chroma.EphemeralClient.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/unit/test_base_vector_store.py -v
```
Expected: `ModuleNotFoundError` — dosya henüz yok.

- [ ] **Step 3: Create stores/ directory and base.py**

```python
# src/graphs/report_agent/subagents/text2sql/stores/__init__.py
# (empty — populated in Task 4)
```

```python
# src/graphs/report_agent/subagents/text2sql/stores/base.py
from abc import ABC, abstractmethod
import chromadb


class BaseVectorStore(ABC):
    """
    Shared infrastructure for in-memory ChromaDB vector stores.
    Subclasses implement initialize() to set up their collection(s)
    and call _build_index() when the collection is empty.
    """

    def __init__(self, embedding_fn):
        self._client = chromadb.EphemeralClient()
        self._embedding_fn = embedding_fn

    @abstractmethod
    def initialize(self, force_recreate: bool = False) -> None:
        """Set up collection(s) and build index if empty."""

    def rebuild(self) -> None:
        """Rebuild index from scratch by re-initializing with force_recreate=True."""
        self.initialize(force_recreate=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit/test_base_vector_store.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/stores/ tests/unit/test_base_vector_store.py
git commit -m "feat: add BaseVectorStore with shared ChromaDB client and rebuild API"
```

---

## Task 3: BusinessRulesStore

**Files:**
- Create: `src/graphs/report_agent/subagents/text2sql/stores/business_rules_store.py`
- Modify: `tests/test_business_rules_cache.py` (import path + API update)

- [ ] **Step 1: Update the existing cache test to the new API**

`tests/test_business_rules_cache.py` dosyasında `vector_store` fixture'ını güncelle:

```python
# tests/test_business_rules_cache.py — fixture değişimi
# ESKİ (satır 49-67):
@pytest.fixture(scope="module")
def vector_store():
    from src.graphs.report_agent.subagents.text2sql.business_rules_vector_store import (
        BusinessRulesVectorStore,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_path = os.path.join(tmpdir, "business_rules.json")
        _create_minimal_rules_file(rules_path)
        store = BusinessRulesVectorStore(
            rules_file_path=rules_path,
            persist_directory=os.path.join(tmpdir, "chroma"),
            similarity_threshold=0.3,
        )
        store.initialize_collections(force_recreate=True)
        store.index_rules()
        yield store

# YENİ:
@pytest.fixture(scope="module")
def vector_store():
    from src.graphs.report_agent.subagents.text2sql.stores.business_rules_store import (
        BusinessRulesStore,
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_path = os.path.join(tmpdir, "business_rules.json")
        _create_minimal_rules_file(rules_path)
        store = BusinessRulesStore(
            rules_file_path=rules_path,
            similarity_threshold=0.3,
        )
        store.initialize(force_recreate=True)
        yield store
```

- [ ] **Step 2: Run updated test to verify it fails (import not found yet)**

```
pytest tests/test_business_rules_cache.py -v
```
Expected: `ModuleNotFoundError: No module named '...stores.business_rules_store'`

- [ ] **Step 3: Create BusinessRulesStore**

Mevcut `text2sql/business_rules_vector_store.py` dosyasının refactor edilmiş hali. Ana değişiklikler:
- `BaseVectorStore`'dan miras al
- Constructor'da `EmbeddingFactory.create_sentence_transformer()` kullan
- `initialize_collections()` + `index_rules()` → `initialize()` + `_build_index()`
- `rebuild_index()` → `rebuild()` (base'den miras alınır)
- `main()` test fonksiyonu kaldırılır
- `preload_embedding_model()` kaldırılır (factory'ye taşındı)

```python
# src/graphs/report_agent/subagents/text2sql/stores/business_rules_store.py
"""
Business Rules Vector Store
============================
Text-to-SQL sistemleri için iş kurallarını semantic olarak arayan sınıf.

- description + modules embed edilir (SQL değil)
- SQL bileşenleri metadata'da saklanır
- Default kurallar ayrı collection'da
- Hybrid search (semantic + keyword)
- Similarity threshold (>0.7)
- Table-aware filtering
- LRU search cache (256 entry, dosya mtime ile invalidate)
"""
import json
import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.factories.embedding_factory import EmbeddingFactory
from src.graphs.report_agent.subagents.text2sql.stores.base import BaseVectorStore

logger = logging.getLogger(__name__)


class BusinessRulesStore(BaseVectorStore):
    """
    İş kurallarını ChromaDB'de tutan ve semantic + keyword hybrid search yapan store.
    İki collection: 'business_rules' (normal) + 'default_business_rules' (her sorguya eklenir).
    """

    def __init__(
        self,
        rules_file_path: str,
        similarity_threshold: float = 0.7,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ):
        embedding_fn = EmbeddingFactory.create_sentence_transformer(embedding_model)
        super().__init__(embedding_fn)

        self.rules_file_path = Path(rules_file_path)
        self.similarity_threshold = similarity_threshold

        self.rules_collection = None
        self.default_rules_collection = None
        self.rules_data = self._load_rules()

        self._search_cache: OrderedDict = OrderedDict()
        self._max_cache_size = 256
        self._cache_lock = threading.Lock()
        stat = os.stat(self.rules_file_path)
        self._rules_file_stat = (stat.st_mtime_ns, stat.st_size)

    # ------------------------------------------------------------------
    # BaseVectorStore interface
    # ------------------------------------------------------------------

    def initialize(self, force_recreate: bool = False) -> None:
        """Two collections: business_rules + default_business_rules."""
        logger.info("Initializing BusinessRulesStore collections...")

        if force_recreate:
            for name in ("business_rules", "default_business_rules"):
                try:
                    self._client.delete_collection(name)
                except Exception:
                    pass

        self.rules_collection = self._client.get_or_create_collection(
            name="business_rules",
            embedding_function=self._embedding_fn,
            metadata={"description": "Business logic rules for Text-to-SQL"},
        )
        self.default_rules_collection = self._client.get_or_create_collection(
            name="default_business_rules",
            embedding_function=self._embedding_fn,
            metadata={"description": "Default rules applied to all queries"},
        )

        if self.rules_collection.count() == 0:
            logger.info("[BUSINESS_RULES] Collections empty, building index...")
            self._build_index()

    def _build_index(self) -> None:
        """JSON → embed → iki collection'a yükle."""
        rules = self.rules_data["business_logic_rules"]
        normal_rules, default_rules = [], []

        for rule in rules:
            text = self._prepare_embedding_text(rule)
            meta = self._prepare_metadata(rule)
            entry = {"id": rule["id"], "text": text, "metadata": meta}
            (default_rules if rule["is_default"] else normal_rules).append(entry)

        if normal_rules:
            self.rules_collection.add(
                ids=[r["id"] for r in normal_rules],
                documents=[r["text"] for r in normal_rules],
                metadatas=[r["metadata"] for r in normal_rules],
            )
            logger.info(f"[BUSINESS_RULES] Indexed {len(normal_rules)} normal rules")

        if default_rules:
            self.default_rules_collection.add(
                ids=[r["id"] for r in default_rules],
                documents=[r["text"] for r in default_rules],
                metadatas=[r["metadata"] for r in default_rules],
            )
            logger.info(f"[BUSINESS_RULES] Indexed {len(default_rules)} default rules")

    # ------------------------------------------------------------------
    # Helpers (unchanged from original)
    # ------------------------------------------------------------------

    def _load_rules(self) -> Dict[str, Any]:
        with open(self.rules_file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _file_has_changed(self) -> bool:
        stat = os.stat(self.rules_file_path)
        key = (stat.st_mtime_ns, stat.st_size)
        if key != self._rules_file_stat:
            self._rules_file_stat = key
            return True
        return False

    def _cache_key(self, user_query: str, n_results: int, use_hybrid: bool,
                   detected_tables=None) -> str:
        tables_part = ",".join(sorted(detected_tables)) if detected_tables else ""
        return f"{user_query}|{n_results}|{use_hybrid}|{tables_part}"

    def clear_cache(self):
        self._search_cache.clear()
        logger.info("[BUSINESS_RULES] Search cache cleared")

    def _prepare_embedding_text(self, rule: Dict[str, Any]) -> str:
        modules = ", ".join(rule["modules"])
        return f"{rule['description']}. Anahtar kelimeler: {modules}"

    def _prepare_metadata(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "rule_id": rule["id"],
            "description": rule["description"],
            "modules": json.dumps(rule["modules"], ensure_ascii=False),
            "related_tables": json.dumps(rule.get("related_tables", []), ensure_ascii=False),
            "is_default": str(rule["is_default"]),
            "sql_aggregation": rule["sql"].get("aggregation") or "",
            "sql_filter": rule["sql"].get("filter") or "",
            "sql_group_by": rule["sql"].get("group_by") or "",
            "sql_select": rule["sql"].get("select") or "",
            "sql_join": rule["sql"].get("join") or "",
            "sql_having": rule["sql"].get("having") or "",
        }

    # ------------------------------------------------------------------
    # Search (unchanged from original)
    # ------------------------------------------------------------------

    def search_rules(
        self,
        query: str,
        n_results: int = 5,
        include_defaults: bool = True,
        table_filter: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        results = []

        if include_defaults:
            default_results = self.default_rules_collection.query(
                query_texts=[query], n_results=100
            )
            for i, rule_id in enumerate(default_results["ids"][0]):
                similarity = 1 - default_results["distances"][0][i]
                results.append({
                    "rule_id": rule_id,
                    "similarity": similarity,
                    "metadata": default_results["metadatas"][0][i],
                    "is_default": True,
                })

        search_results = self.rules_collection.query(
            query_texts=[query], n_results=n_results * 2, where=None
        )
        for i, rule_id in enumerate(search_results["ids"][0]):
            similarity = 1 - search_results["distances"][0][i]
            if similarity < self.similarity_threshold:
                continue
            metadata = search_results["metadatas"][0][i]
            if table_filter:
                related = json.loads(metadata["related_tables"])
                if "*" not in related and not any(t in related for t in table_filter):
                    continue
            results.append({
                "rule_id": rule_id,
                "similarity": similarity,
                "metadata": metadata,
                "is_default": False,
            })

        results = sorted(results, key=lambda x: x["similarity"], reverse=True)
        non_default = [r for r in results if not r["is_default"]][:n_results]
        defaults = [r for r in results if r["is_default"]]
        return defaults + non_default

    def keyword_search(self, keywords: List[str], n_results: int = 5) -> List[Dict[str, Any]]:
        results = []
        for keyword in keywords:
            sr = self.rules_collection.get(where_document={"$contains": keyword.lower()})
            for i, rule_id in enumerate(sr["ids"]):
                results.append({
                    "rule_id": rule_id,
                    "similarity": 0.9,
                    "metadata": sr["metadatas"][i],
                    "is_default": False,
                    "match_type": "keyword",
                })
        seen, unique = set(), []
        for r in results:
            if r["rule_id"] not in seen:
                seen.add(r["rule_id"])
                unique.append(r)
        return unique[:n_results]

    def merge_sql_components(
        self,
        rules: List[Dict[str, Any]],
        date_column: str = "created_at",
        amount_column: str = "amount",
    ) -> Dict[str, str]:
        merged = {k: [] for k in ("aggregation", "filter", "group_by", "select", "join", "having")}
        seen_components = {k: set() for k in ("filter", "join", "group_by", "select")}

        for rule in rules:
            meta = rule["metadata"]
            for comp in merged:
                value = meta.get(f"sql_{comp}", "").strip()
                if not value:
                    continue
                value = value.replace("{date_column}", date_column).replace("{amount_column}", amount_column)
                if comp in seen_components:
                    if value in seen_components[comp]:
                        continue
                    seen_components[comp].add(value)
                merged[comp].append(value)

        final: Dict[str, str] = {}
        if merged["aggregation"]:
            final["aggregation"] = merged["aggregation"][0]
        if merged["filter"]:
            final["filter"] = " AND ".join(f"({f})" for f in merged["filter"])
        if merged["group_by"]:
            final["group_by"] = ", ".join(merged["group_by"])
        if merged["select"]:
            final["select"] = ", ".join(merged["select"])
        if merged["join"]:
            final["join"] = " ".join(merged["join"])
        if merged["having"]:
            final["having"] = " AND ".join(f"({h})" for h in merged["having"])
        return final

    def get_relevant_rules_for_query(
        self,
        user_query: str,
        detected_tables: Optional[List[str]] = None,
        n_results: int = 5,
        use_hybrid: bool = True,
    ) -> Dict[str, Any]:
        with self._cache_lock:
            if self._file_has_changed():
                self._search_cache.clear()
                logger.info("[BUSINESS_RULES] Rules file changed, cache invalidated")
            cache_key = self._cache_key(user_query, n_results, use_hybrid, detected_tables)
            if cache_key in self._search_cache:
                logger.debug(f"[BUSINESS_RULES] Cache hit for: {user_query[:50]}")
                return self._search_cache[cache_key]

        semantic_results = self.search_rules(
            query=user_query, n_results=n_results,
            include_defaults=True, table_filter=detected_tables,
        )
        keyword_results = []
        if use_hybrid:
            keywords = [k for k in user_query.lower().split() if len(k) > 3]
            if keywords:
                keyword_results = self.keyword_search(keywords, n_results=3)

        seen_ids: set = set()
        unique_results = []
        for r in semantic_results + keyword_results:
            if r["rule_id"] not in seen_ids:
                seen_ids.add(r["rule_id"])
                unique_results.append(r)

        merged_sql = self.merge_sql_components(unique_results)
        default_count = sum(1 for r in unique_results if r["is_default"])

        individual_rules = []
        seen_individual: set = set()
        for r in unique_results:
            rid = r["rule_id"]
            if rid in seen_individual:
                continue
            seen_individual.add(rid)
            meta = r.get("metadata", {})
            individual_rules.append({
                "id": rid,
                "description": meta.get("description", ""),
                "sql": {
                    "aggregation": meta.get("sql_aggregation") or None,
                    "filter": meta.get("sql_filter") or None,
                    "group_by": meta.get("sql_group_by") or None,
                    "select": meta.get("sql_select") or None,
                    "join": meta.get("sql_join") or None,
                    "having": meta.get("sql_having") or None,
                },
                "is_default": r.get("is_default", False),
                "source": "default" if r.get("is_default") else "semantic",
            })

        result = {
            "individual_rules": individual_rules,
            "rules": unique_results,
            "merged_sql": merged_sql,
            "default_count": default_count,
            "semantic_count": len(unique_results) - default_count,
            "total_count": len(unique_results),
        }
        with self._cache_lock:
            if len(self._search_cache) >= self._max_cache_size:
                self._search_cache.popitem(last=False)
            self._search_cache[cache_key] = result
        return result
```

- [ ] **Step 4: Run cache tests to verify they pass**

```
pytest tests/test_business_rules_cache.py -v
```
Expected: 2+ tests PASS. (Gerçek SentenceTransformer model gerektirir — model cache'li değilse yavaş olabilir.)

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/stores/business_rules_store.py \
        tests/test_business_rules_cache.py
git commit -m "feat: add BusinessRulesStore extending BaseVectorStore"
```

---

## Task 4: TermStore + stores/__init__.py

**Files:**
- Create: `src/graphs/report_agent/subagents/text2sql/stores/term_store.py`
- Modify: `src/graphs/report_agent/subagents/text2sql/stores/__init__.py`

- [ ] **Step 1: Create TermStore**

Mevcut `term_vector_store.py`'nin refactor edilmiş hali. Değişiklikler:
- `BaseVectorStore`'dan miras al
- Constructor'da `EmbeddingFactory.create_sentence_transformer()` kullan
- `persist_directory` parametresi kaldırılır
- `initialize()` → base interface'i implement eder
- `index_terms()` → `_build_index()` olarak rename edilir
- Diğer tüm metodlar (`resolve`, `_keyword_pre_resolve`, `_semantic_search`, `_apply_conflict_resolution`) değişmez

```python
# src/graphs/report_agent/subagents/text2sql/stores/term_store.py
"""
Term Vector Store
=================
Kullanıcı sorgusundaki Türkçe iş terimlerini semantik olarak tespit eder.

JSON → ChromaDB (sentence-transformers embedding)
resolve(user_query) → TermResolverOutput
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.factories.embedding_factory import EmbeddingFactory
from src.graphs.report_agent.subagents.text2sql.stores.base import BaseVectorStore

logger = logging.getLogger(__name__)

_DEFAULT_COLLECTION = "term_dictionary"
_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_SIMILARITY_THRESHOLD = 0.75
_TOP_K = 15
_TR_CHARS = r"a-zA-ZçğıöşüÇĞİÖŞÜ"


# Data classes — unchanged from term_vector_store.py
@dataclass
class AmbiguousMatch:
    term: str
    user_query: str
    options: List[Dict[str, Any]]


@dataclass
class TermResolverOutput:
    term_filters: List[Dict[str, Any]] = field(default_factory=list)
    candidate_filter_terms: List[Dict[str, Any]] = field(default_factory=list)
    hints_text: str = "Özel terim eşleşmesi bulunamadı."
    ambiguous: List[AmbiguousMatch] = field(default_factory=list)


@dataclass
class TermCandidate:
    term_id: str
    category: str
    term: str
    column: str
    specificity: float
    hint: str
    filter_structured: Optional[Dict[str, Any]]
    ambiguous_columns: List[Dict[str, Any]]
    similarity: float

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguous_columns)

    @property
    def sort_key(self) -> float:
        return self.similarity * self.specificity


class TermStore(BaseVectorStore):
    """
    term_dictionary.json → ChromaDB semantic index.

    store = TermStore(dict_path=...) 
    store.initialize()           # graph startup'ta bir kez
    output = store.resolve(query)  # her sorguda
    """

    def __init__(
        self,
        dict_path: str | Path,
        similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
        embedding_model: str = _DEFAULT_MODEL,
    ):
        embedding_fn = EmbeddingFactory.create_sentence_transformer(embedding_model)
        super().__init__(embedding_fn)

        self.dict_path = Path(dict_path)
        self.similarity_threshold = similarity_threshold
        self._collection = None
        self._terms_data: List[Dict[str, Any]] = []
        self._keyword_patterns: Dict[str, re.Pattern] = {}

    # ------------------------------------------------------------------
    # BaseVectorStore interface
    # ------------------------------------------------------------------

    def initialize(self, force_recreate: bool = False) -> None:
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
        if not self._terms_data:
            logger.error(f"[TERM_STORE] Dict empty or unreadable: {self.dict_path}")
            return

        self._keyword_patterns = {
            alias.lower(): re.compile(
                rf"(?<![{_TR_CHARS}]){re.escape(alias.lower())}(?:ları|leri|lar|ler|su|sı|si|sü|nın|nin|nun|nün|dan|den|tan|ten|da|de|ta|te|ya|ye|yı|yi|yu|yü|ı|i|u|ü|a|e)?(?![{_TR_CHARS}])"
            )
            for entry in self._terms_data
            if not entry.get("filter_structured") and not entry.get("ambiguous_columns")
            for alias in [entry["term"]] + entry.get("aliases", [])
        }

        if self._collection.count() == 0:
            logger.info("[TERM_STORE] Collection empty, building index...")
            self._build_index()
        else:
            logger.info(f"[TERM_STORE] Collection ready ({self._collection.count()} terms)")

    def _build_index(self) -> None:
        """term_dictionary.json → embed → ChromaDB collection."""
        if not self._terms_data:
            self._terms_data = self._load_dict()

        ids, documents, metadatas = [], [], []
        for entry in self._terms_data:
            term_id = entry["id"]
            embedding_text = entry.get("embedding_text") or self._build_embedding_text(entry)
            metadata = {
                "term_id": term_id,
                "category": entry.get("category", ""),
                "term": entry["term"],
                "column": entry.get("column", ""),
                "specificity": str(entry.get("specificity", 1.0)),
                "hint": entry.get("hint", ""),
                "filter_structured_json": json.dumps(entry.get("filter_structured") or {}, ensure_ascii=False),
                "ambiguous_columns_json": json.dumps(entry.get("ambiguous_columns") or [], ensure_ascii=False),
            }
            ids.append(term_id)
            documents.append(embedding_text)
            metadatas.append(metadata)

        self._collection.add(ids=ids, documents=documents, metadatas=metadatas)
        logger.info(f"[TERM_STORE] Indexed {len(ids)} terms")

    # ------------------------------------------------------------------
    # Public API + internals — unchanged from term_vector_store.py
    # ------------------------------------------------------------------

    def resolve(self, user_query: str) -> TermResolverOutput:
        keyword_pre_resolved = self._keyword_pre_resolve(user_query)
        candidates = self._semantic_search(user_query)
        return self._apply_conflict_resolution(candidates, user_query, keyword_pre_resolved)

    def _keyword_pre_resolve(self, user_query: str) -> Dict[str, "TermCandidate"]:
        if not self._terms_data:
            return {}
        query_lower = user_query.lower()
        pre_resolved: Dict[str, TermCandidate] = {}
        consumed_spans: list[tuple[int, int]] = []

        alias_entries: list[tuple[str, dict]] = []
        for entry in self._terms_data:
            if entry.get("filter_structured") or entry.get("ambiguous_columns"):
                continue
            if not entry.get("column"):
                continue
            for alias in [entry["term"]] + entry.get("aliases", []):
                alias_entries.append((alias.lower(), entry))
        alias_entries.sort(key=lambda x: len(x[0]), reverse=True)

        for alias, entry in alias_entries:
            column = entry["column"]
            if column in pre_resolved:
                continue
            pat = self._keyword_patterns.get(alias)
            if not pat:
                continue
            match = pat.search(query_lower)
            if not match:
                continue
            m_start, m_end = match.start(), match.end()
            if any(cs <= m_start < ce or cs < m_end <= ce for cs, ce in consumed_spans):
                continue
            consumed_spans.append((m_start, m_end))
            pre_resolved[column] = TermCandidate(
                term_id=entry["id"],
                category=entry.get("category", ""),
                term=entry["term"],
                column=column,
                specificity=float(entry.get("specificity", 1.0)),
                hint=entry.get("hint", ""),
                filter_structured=None,
                ambiguous_columns=[],
                similarity=1.0,
            )
        return pre_resolved

    def _semantic_search(self, user_query: str) -> List[TermCandidate]:
        if self._collection is None:
            logger.warning("[TERM_STORE] Not initialized, returning empty")
            return []
        results = self._collection.query(
            query_texts=[user_query],
            n_results=min(_TOP_K, self._collection.count() or 1),
        )
        candidates: List[TermCandidate] = []
        for i, term_id in enumerate(results["ids"][0]):
            similarity = 1 - results["distances"][0][i]
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
        return candidates

    def _apply_conflict_resolution(
        self,
        candidates: List[TermCandidate],
        user_query: str,
        keyword_pre_resolved: Optional[Dict[str, "TermCandidate"]] = None,
    ) -> TermResolverOutput:
        sorted_candidates = sorted(candidates, key=lambda c: c.sort_key, reverse=True)
        resolved_columns: Dict[str, TermCandidate] = dict(keyword_pre_resolved or {})
        term_filters: List[Dict[str, Any]] = []
        candidate_filter_terms: List[Dict[str, Any]] = []
        filter_hint_lines: List[str] = []
        column_hint_lines: List[str] = [
            f'- "{cand.term}" (keyword) [{col}] → {cand.hint}'
            for col, cand in resolved_columns.items()
        ]
        ambiguous: List[AmbiguousMatch] = []

        for candidate in sorted_candidates:
            if not candidate.is_ambiguous and candidate.column:
                if candidate.column not in resolved_columns:
                    resolved_columns[candidate.column] = candidate
                    if candidate.filter_structured:
                        fs = dict(candidate.filter_structured)
                        fs.setdefault("logical_operator", "AND")
                        term_filters.append(fs)
                        candidate_filter_terms.append({
                            "term_id": candidate.term_id,
                            "term": candidate.term,
                            "column": candidate.column,
                            "filter_structured": candidate.filter_structured,
                            "hint": candidate.hint,
                        })
                        col_val = (
                            f"{candidate.filter_structured.get('column')} "
                            f"{candidate.filter_structured.get('operator')} "
                            f"{candidate.filter_structured.get('value', '')}".strip()
                        )
                        filter_hint_lines.append(f"- {col_val}  ({candidate.term})")
                    else:
                        column_hint_lines.append(
                            f'- "{candidate.term}" [{candidate.column}] → {candidate.hint}'
                        )
                continue

            if candidate.is_ambiguous:
                amb_cols = [c["column"] for c in candidate.ambiguous_columns]
                already_resolved = [c for c in amb_cols if c in resolved_columns]
                if already_resolved:
                    for col in already_resolved:
                        winner = resolved_columns[col]
                        column_hint_lines.append(
                            f'- "{candidate.term}" → "{winner.term}" ile [{col}] çözüldü (suppressed)'
                        )
                else:
                    ambiguous.append(AmbiguousMatch(
                        term=candidate.term, user_query=user_query,
                        options=candidate.ambiguous_columns,
                    ))
                    column_hint_lines.append(
                        f'- "{candidate.term}" → belirsiz kolon, kullanıcıya sorulacak'
                    )

        hints_sections: List[str] = []
        if filter_hint_lines:
            hints_sections.append(
                "## PYTHON-YÖNETİMLİ FİLTRELER "
                "(sen filters'a EKLEME — Python garantili uygular)\n"
                + "\n".join(filter_hint_lines)
            )
        if column_hint_lines:
            hints_sections.append(
                "## KOLON İPUÇLARI "
                "(LLM için rehber — aggregations/group_by kararlarında kullan)\n"
                + "\n".join(column_hint_lines)
            )
        hints_text = "\n\n".join(hints_sections) if hints_sections else "Özel terim eşleşmesi bulunamadı."

        return TermResolverOutput(
            term_filters=term_filters,
            candidate_filter_terms=candidate_filter_terms,
            hints_text=hints_text,
            ambiguous=ambiguous,
        )

    def _load_dict(self) -> List[Dict[str, Any]]:
        try:
            with open(self.dict_path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("terms", [])
        except Exception as e:
            logger.error(f"[TERM_STORE] Failed to load dict: {e}")
            return []

    @staticmethod
    def _build_embedding_text(entry: Dict[str, Any]) -> str:
        parts = [entry["term"]] + entry.get("aliases", [])
        return ", ".join(parts)
```

- [ ] **Step 2: Update stores/__init__.py**

```python
# src/graphs/report_agent/subagents/text2sql/stores/__init__.py
from .business_rules_store import BusinessRulesStore
from .term_store import TermStore

__all__ = ["BusinessRulesStore", "TermStore"]
```

- [ ] **Step 3: Verify both stores are importable**

```
python -c "from src.graphs.report_agent.subagents.text2sql.stores import BusinessRulesStore, TermStore; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/stores/
git commit -m "feat: add TermStore extending BaseVectorStore"
```

---

## Task 5: Move Data Files

**Files:**
- Move: `src/graphs/report_agent/data/business_rules.json` → `src/graphs/report_agent/data/vector/business_rules.json`
- Move: `src/graphs/report_agent/subagents/text2sql/term_dictionary.json` → `src/graphs/report_agent/data/vector/term_dictionary.json`

- [ ] **Step 1: Git mv her iki dosyayı**

```bash
mkdir -p src/graphs/report_agent/data/vector
git mv src/graphs/report_agent/data/business_rules.json \
       src/graphs/report_agent/data/vector/business_rules.json

git mv src/graphs/report_agent/subagents/text2sql/term_dictionary.json \
       src/graphs/report_agent/data/vector/term_dictionary.json
```

- [ ] **Step 2: Verify files exist at new locations**

```bash
ls src/graphs/report_agent/data/vector/
```
Expected: `business_rules.json  term_dictionary.json`

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: move vector data files to data/vector/"
```

---

## Task 6: Update text2sql/graph.py

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/graph.py`

- [ ] **Step 1: Update imports, remove chroma_persist_dir, update store initialization**

`src/graphs/report_agent/subagents/text2sql/graph.py` dosyasında şu değişiklikler:

```python
# ESKİ imports (satır 24-25):
from src.graphs.report_agent.subagents.text2sql.business_rules_vector_store import BusinessRulesVectorStore
# (TermVectorStore ayrı satırda içeride import edilir)

# YENİ imports — dosyanın üstüne ekle:
from src.graphs.report_agent.subagents.text2sql.stores import BusinessRulesStore, TermStore
```

```python
# ESKİ fonksiyon signature (satır 61-68):
def build_text2sql_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    connection_string: str,
    business_rules_path: str,
    chroma_persist_dir: str,
):

# YENİ — chroma_persist_dir kaldırıldı:
def build_text2sql_graph(
    llm,
    table_name: str,
    column_metadata: Dict[str, Any],
    connection_string: str,
    business_rules_path: str,
):
```

```python
# ESKİ store initialization (satır 88-106):
vector_store = BusinessRulesVectorStore(
    rules_file_path=business_rules_path,
    persist_directory=chroma_persist_dir,
)
vector_store.initialize_collections()
if vector_store.rules_collection.count() == 0:
    logger.info("[TEXT2SQL] ChromaDB collections empty, building index...")
    vector_store.index_rules()

business_rules = create_business_rules_node(vector_store, llm=llm)
term_vector_store = TermVectorStore(
    dict_path=Path(__file__).parent / "term_dictionary.json",
    persist_directory=chroma_persist_dir,
)
term_vector_store.initialize()
term_resolver = create_term_resolver_node(term_vector_store)

# YENİ:
_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "vector"

vector_store = BusinessRulesStore(rules_file_path=business_rules_path)
vector_store.initialize()
business_rules = create_business_rules_node(vector_store, llm=llm)

term_store = TermStore(dict_path=_DATA_DIR / "term_dictionary.json")
term_store.initialize()
term_resolver = create_term_resolver_node(term_store)
```

Ayrıca docstring'deki `chroma_persist_dir` satırını sil.

- [ ] **Step 2: Verify import of text2sql graph works**

```
python -c "from src.graphs.report_agent.subagents.text2sql.graph import build_text2sql_graph; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/graph.py
git commit -m "refactor(text2sql): use stores/ imports, remove chroma_persist_dir"
```

---

## Task 7: Update report_agent/graph.py + configuration.py

**Files:**
- Modify: `src/graphs/report_agent/graph.py`
- Modify: `src/graphs/report_agent/configuration.py`

- [ ] **Step 1: Update configuration.py business_rules_path default**

`src/graphs/report_agent/configuration.py` satır 350-351'de:

```python
# ESKİ:
business_rules_path: str = Field(
    default="./src/graphs/report_agent/data/business_rules.json",

# YENİ:
business_rules_path: str = Field(
    default="./src/graphs/report_agent/data/vector/business_rules.json",
```

- [ ] **Step 2: Update report_agent/graph.py**

`src/graphs/report_agent/graph.py` dosyasında 3 değişiklik:

**2a. build_report_agent_graph signature — chroma_persist_dir kaldır:**
```python
# ESKİ (satır 76-77):
    business_rules_path: str,
    chroma_persist_dir: str,

# YENİ:
    business_rules_path: str,
```

**2b. build_text2sql_graph çağrısı — chroma_persist_dir kaldır:**
```python
# ESKİ (satır 85-91):
    text2sql = build_text2sql_graph(
        llm=llm,
        table_name=table_name,
        column_metadata=column_metadata,
        connection_string=connection_string,
        business_rules_path=effective_business_rules_path,
        chroma_persist_dir=chroma_persist_dir,
    )

# YENİ:
    text2sql = build_text2sql_graph(
        llm=llm,
        table_name=table_name,
        column_metadata=column_metadata,
        connection_string=connection_string,
        business_rules_path=effective_business_rules_path,
    )
```

**2c. ReportAgentGraphBuilder — chroma_persist_dir kaldır (satır 179-213):**
```python
# ESKİ create() içi (satır 179-188):
        business_rules_path = str(
            project_root / "src" / "graphs" / "report_agent" / "data" / "business_rules.json"
        )
        chroma_persist_dir = str(project_root / "data" / "vector_store")
        return cls(
            llm=llm,
            app_config=app_config,
            business_rules_path=business_rules_path,
            chroma_persist_dir=chroma_persist_dir,
        )

# YENİ:
        business_rules_path = str(
            project_root / "src" / "graphs" / "report_agent" / "data" / "vector" / "business_rules.json"
        )
        return cls(
            llm=llm,
            app_config=app_config,
            business_rules_path=business_rules_path,
        )
```

```python
# ESKİ __init__ (satır 191-195):
    def __init__(self, llm, app_config, business_rules_path, chroma_persist_dir):
        self._llm = llm
        self._app_config = app_config
        self._business_rules_path = business_rules_path
        self._chroma_persist_dir = chroma_persist_dir

# YENİ:
    def __init__(self, llm, app_config, business_rules_path):
        self._llm = llm
        self._app_config = app_config
        self._business_rules_path = business_rules_path
```

```python
# ESKİ build_graph() çağrısı (satır 206-212):
        return build_report_agent_graph(
            ...
            business_rules_path=self._business_rules_path,
            chroma_persist_dir=self._chroma_persist_dir,
        )

# YENİ:
        return build_report_agent_graph(
            ...
            business_rules_path=self._business_rules_path,
        )
```

- [ ] **Step 3: Verify report_agent graph imports cleanly**

```
python -c "from src.graphs.report_agent.graph import build_report_agent_graph; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/graphs/report_agent/graph.py src/graphs/report_agent/configuration.py
git commit -m "refactor(report_agent): remove chroma_persist_dir, update data/vector path"
```

---

## Task 8: Update routing/graph.py

**Files:**
- Modify: `src/graphs/routing/graph.py`
- Modify: `tests/unit/test_vectorstore_auto_init.py` (patch target güncelleme)

- [ ] **Step 1: Replace inline OpenAIEmbeddings with EmbeddingFactory.create_openai()**

`src/graphs/routing/graph.py` dosyasında `_setup_vectorstore()` metodunda:

```python
# ESKİ import (dosya üstünde):
from langchain_openai import OpenAIEmbeddings

# YENİ — bu import satırını kaldır, embedding_factory import ekle:
from src.factories.embedding_factory import EmbeddingFactory
```

```python
# ESKİ (satır 245-249 civarı):
            embeddings = OpenAIEmbeddings(
                model=self._app_config.embedding.model,
                openai_api_key=self._app_config.embedding.api_key,
                base_url=self._app_config.embedding.base_url,
            )

# YENİ:
            embeddings = EmbeddingFactory.create_openai(
                model=self._app_config.embedding.model,
                api_key=self._app_config.embedding.api_key,
                base_url=self._app_config.embedding.base_url,
            )
```

- [ ] **Step 2: Update test patch targets**

`tests/unit/test_vectorstore_auto_init.py` dosyasında tüm `@patch("src.graphs.routing.graph.OpenAIEmbeddings")` satırlarını güncelle:

```python
# ESKİ (her test metodunun @patch decorator'ında):
@patch("src.graphs.routing.graph.OpenAIEmbeddings")

# YENİ:
@patch("src.factories.embedding_factory.OpenAIEmbeddings")
```

Bu 4 test metodunda geçiyor — hepsinde değiştir:
- `test_auto_creates_when_collection_missing`
- `test_existing_collection_no_auto_create`
- `test_returns_none_when_catalog_missing`
- `test_empty_collection_triggers_re_creation`

- [ ] **Step 3: Run routing tests to verify they pass**

```
pytest tests/unit/test_vectorstore_auto_init.py -v
```
Expected: 7 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add src/graphs/routing/graph.py tests/unit/test_vectorstore_auto_init.py
git commit -m "refactor(routing): use EmbeddingFactory.create_openai() in vectorstore setup"
```

---

## Task 9: Update api/main.py

**Files:**
- Modify: `src/api/main.py`

- [ ] **Step 1: Update preload_embedding_model import**

`src/api/main.py` dosyasında:

```python
# ESKİ (satır 35):
from src.graphs.report_agent.business_rules_vector_store import preload_embedding_model

# YENİ:
from src.factories.embedding_factory import preload_embedding_model
```

- [ ] **Step 2: Verify api/main.py imports cleanly**

```
python -c "import src.api.main; print('OK')" 2>&1 | head -5
```
Expected: `OK` veya sadece expected startup warnings (DB bağlantısı yoksa hata olabilir ama import hatası olmaz).

- [ ] **Step 3: Commit**

```bash
git add src/api/main.py
git commit -m "refactor(api): import preload_embedding_model from EmbeddingFactory"
```

---

## Task 10: Delete Old Files

**Files:**
- Delete: `src/graphs/report_agent/business_rules_vector_store.py`
- Delete: `src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py`
- Delete: `src/graphs/report_agent/subagents/text2sql/term_vector_store.py`

- [ ] **Step 1: Verify no remaining imports of old files**

```bash
grep -rn "from src.graphs.report_agent.business_rules_vector_store\|from src.graphs.report_agent.subagents.text2sql.business_rules_vector_store\|from src.graphs.report_agent.subagents.text2sql.term_vector_store" src/ tests/ --include="*.py"
```
Expected: No output. Eğer çıktı varsa, önce o dosyaları güncelle.

- [ ] **Step 2: Git rm eski dosyalar**

```bash
git rm src/graphs/report_agent/business_rules_vector_store.py
git rm src/graphs/report_agent/subagents/text2sql/business_rules_vector_store.py
git rm src/graphs/report_agent/subagents/text2sql/term_vector_store.py
```

- [ ] **Step 3: Run full test suite**

```
pytest tests/ -v --ignore=tests/integration -x 2>&1 | tail -20
```
Expected: Tüm testler PASS, import hatası yok.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "refactor: delete old vector store files — replaced by stores/ package"
```

---

## Verification Checklist

Son kontroller:

- [ ] `pytest tests/unit/test_embedding_factory.py -v` → PASS
- [ ] `pytest tests/unit/test_base_vector_store.py -v` → PASS
- [ ] `pytest tests/test_business_rules_cache.py -v` → PASS
- [ ] `pytest tests/unit/test_vectorstore_auto_init.py -v` → PASS
- [ ] `grep -rn "business_rules_vector_store\|term_vector_store" src/ --include="*.py"` → No output
- [ ] `ls src/graphs/report_agent/data/vector/` → `business_rules.json  term_dictionary.json`
- [ ] `ls src/graphs/report_agent/subagents/text2sql/stores/` → `__init__.py  base.py  business_rules_store.py  term_store.py`
