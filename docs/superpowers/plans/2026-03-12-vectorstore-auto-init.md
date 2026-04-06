# Vectorstore Auto-Initialization - Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-create the `forza_web_pages` Chroma collection from `data/forza.json` when missing, so routing never silently degrades.

**Architecture:** When `_setup_vectorstore()` detects a missing collection, it calls `_auto_create_collection()` which loads `data/forza.json`, creates LangChain Documents with all metadata fields routing nodes need (`title`, `url`/`url_route`, `category`, `page_id`, `document_type`, `sub_page_type`, `parent_page_id`, `has_parameters`, `parameter_count`, `url_parameters`, `keywords`), and uses `Chroma.from_documents(client=chroma_client)` to build the collection using the already-created client (avoids dual-client locking). Subsequent startups find the existing collection and skip creation. Graceful degradation preserved: if `forza.json` is also missing, vectorstore stays `None`.

**Tech Stack:** Python, ChromaDB 1.3.4, LangChain, langchain-chroma, OpenAIEmbeddings, pytest

**Root Cause:** ChromaDB major version upgrade (0.x → 1.3.4) wiped collection metadata during migration. HNSW binary files remain orphaned in `data/vector_store/065609e6-*/`. Manual script-based creation is disconnected from runtime, causing silent routing degradation.

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/graphs/routing/graph.py:164-233` | Add `_create_documents_from_catalog()`, `_auto_create_collection()` + update `_setup_vectorstore()` fallback |
| Create | `tests/unit/test_vectorstore_auto_init.py` | Tests for auto-initialization behavior |

---

## Chunk 1: Vectorstore Auto-Initialization

### Task 1: Write failing tests for auto-initialization

**Files:**
- Create: `tests/unit/test_vectorstore_auto_init.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for RoutingGraph vectorstore auto-initialization."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.graphs.routing.graph import RoutingGraph


SAMPLE_CATALOG = {
    "name": "Test Catalog",
    "version": "0.0.1",
    "total_pages": 3,
    "web_pages_catalog": [
        {
            "metadata": {
                "page_id": "ana_sayfa",
                "title": "Ana Sayfa",
                "url_route": "{base_url}/dashboard",
                "category": "Panolar",
                "page_type": "main_page",
            },
            "embedding_content": "Ana sayfa dashboard",
            "structured_data": {
                "functions": ["Dashboard görüntüleme"],
                "keywords": ["anasayfa", "dashboard"],
                "related_terms": [],
                "user_types": [],
            },
            "user_expressions": ["anasayfayı aç"],
        },
        {
            "metadata": {
                "page_id": "cari_detay",
                "title": "Cari Detay",
                "url_route": "{base_url}/customer/{cari_id}",
                "category": "Cariler",
                "page_type": "detail_page",
                "url_parameters": {
                    "cari_id": {
                        "type": "integer",
                        "description": "Cari ID",
                        "required": True,
                        "endpoint": "/api/customers",
                    }
                },
            },
            "embedding_content": "Cari detay sayfası",
            "structured_data": {
                "functions": ["Cari bilgi görüntüleme"],
                "keywords": ["cari", "müşteri"],
                "related_terms": [],
                "user_types": [],
            },
            "user_expressions": ["cari detayını göster"],
        },
        {
            "metadata": {
                "page_id": "cari_evraklar",
                "title": "Cari Evraklar",
                "url_route": "{base_url}/customer/{cari_id}/documents",
                "category": "Cariler",
                "page_type": "sub_page",
                "parent_page_id": "cari_detay",
                "sub_page_type": "tab",
                "url_parameters": {
                    "cari_id": {
                        "type": "integer",
                        "description": "Cari ID",
                        "required": True,
                        "endpoint": "/api/customers",
                    }
                },
            },
            "embedding_content": "Cari evrakları sekmesi",
            "structured_data": {
                "functions": ["Evrak görüntüleme"],
                "keywords": ["evrak", "fatura"],
                "related_terms": [],
                "user_types": [],
            },
            "user_expressions": ["evrakları göster"],
        },
    ],
}


def _make_graph_instance():
    """Create a RoutingGraph instance bypassing __init__."""
    graph = RoutingGraph.__new__(RoutingGraph)
    graph.llm = MagicMock()
    graph.config = MagicMock()
    return graph


class TestCreateDocumentsFromCatalog:
    """Test _create_documents_from_catalog document creation logic."""

    def test_creates_documents_with_correct_metadata_fields(self):
        """Documents must have all metadata fields routing nodes expect."""
        graph = _make_graph_instance()
        documents = graph._create_documents_from_catalog(SAMPLE_CATALOG)

        assert len(documents) == 3

        # First page - main_page, no parameters
        doc0 = documents[0]
        assert doc0.metadata["page_id"] == "ana_sayfa"
        assert doc0.metadata["title"] == "Ana Sayfa"
        assert doc0.metadata["url"] == "{base_url}/dashboard"
        assert doc0.metadata["url_route"] == "{base_url}/dashboard"
        assert doc0.metadata["category"] == "Panolar"
        assert doc0.metadata["document_type"] == "main_page"
        assert doc0.metadata["has_parameters"] is False
        assert doc0.metadata["parameter_count"] == 0
        assert doc0.metadata["url_parameters"] == ""
        assert "anasayfa" in doc0.metadata["keywords"]

    def test_creates_documents_with_url_parameters(self):
        """Pages with url_parameters must have parameter metadata."""
        graph = _make_graph_instance()
        documents = graph._create_documents_from_catalog(SAMPLE_CATALOG)

        # Second page - has parameters
        doc1 = documents[1]
        assert doc1.metadata["has_parameters"] is True
        assert doc1.metadata["parameter_count"] == 1
        assert doc1.metadata["url_parameters"] != ""
        # url_parameters should be valid JSON
        params = json.loads(doc1.metadata["url_parameters"])
        assert "cari_id" in params

    def test_creates_documents_with_sub_page_metadata(self):
        """Sub-pages must have document_type, sub_page_type, parent_page_id."""
        graph = _make_graph_instance()
        documents = graph._create_documents_from_catalog(SAMPLE_CATALOG)

        # Third page - sub_page
        doc2 = documents[2]
        assert doc2.metadata["document_type"] == "sub_page"
        assert doc2.metadata["sub_page_type"] == "tab"
        assert doc2.metadata["parent_page_id"] == "cari_detay"

    def test_main_page_has_empty_sub_page_fields(self):
        """Main pages should have empty sub-page fields."""
        graph = _make_graph_instance()
        documents = graph._create_documents_from_catalog(SAMPLE_CATALOG)

        doc0 = documents[0]
        assert doc0.metadata["document_type"] == "main_page"
        assert doc0.metadata["sub_page_type"] == ""
        assert doc0.metadata["parent_page_id"] == ""

    def test_page_content_includes_embedding_and_extras(self):
        """Document content should include embedding_content + keywords + expressions."""
        graph = _make_graph_instance()
        documents = graph._create_documents_from_catalog(SAMPLE_CATALOG)

        content = documents[0].page_content
        assert "Ana sayfa dashboard" in content
        assert "anasayfa" in content
        assert "anasayfayı aç" in content

    def test_empty_catalog_returns_empty_list(self):
        """Empty catalog produces no documents."""
        graph = _make_graph_instance()
        empty_catalog = {"web_pages_catalog": []}
        documents = graph._create_documents_from_catalog(empty_catalog)
        assert documents == []


class TestSetupVectorstoreAutoInit:
    """Test that _setup_vectorstore auto-creates collection when missing."""

    def _setup_graph_with_mocks(self, mock_config, mock_chromadb):
        """Common setup for _setup_vectorstore tests."""
        mock_config.vector_store.persist_directory = "./data/vector_store"
        mock_config.embedding.model = "text-embedding-3-large"
        mock_config.embedding.api_key = "test-key"
        mock_config.embedding.base_url = "https://api.openai.com/v1"

        graph = _make_graph_instance()
        # _get_base_path → project root (test file is at tests/unit/test_*.py)
        base_path = Path(__file__).resolve().parent.parent.parent
        graph._get_base_path = MagicMock(return_value=base_path)
        return graph

    @patch("src.graphs.routing.graph.Chroma")
    @patch("src.graphs.routing.graph.chromadb")
    @patch("src.graphs.routing.graph.OpenAIEmbeddings")
    @patch("src.graphs.routing.graph.config")
    def test_auto_creates_when_collection_missing(
        self, mock_config, mock_embeddings_cls, mock_chromadb, mock_chroma_cls
    ):
        """When get_collection raises, should attempt auto-creation from forza.json."""
        graph = self._setup_graph_with_mocks(mock_config, mock_chromadb)

        # Chroma client that says collection doesn't exist
        mock_client = MagicMock()
        mock_client.get_collection.side_effect = Exception("Collection forza_web_pages does not exist")
        mock_chromadb.PersistentClient.return_value = mock_client

        # Mock Chroma.from_documents to return a vectorstore
        mock_vectorstore = MagicMock()
        mock_chroma_cls.from_documents.return_value = mock_vectorstore

        result = graph._setup_vectorstore()

        # Should have called Chroma.from_documents (auto-creation)
        assert mock_chroma_cls.from_documents.called, \
            "_setup_vectorstore should auto-create collection from forza.json"
        # Should pass client= (not persist_directory) to avoid dual-client
        call_kwargs = mock_chroma_cls.from_documents.call_args[1]
        assert "client" in call_kwargs, "Should pass client= to from_documents"
        assert call_kwargs["client"] is mock_client
        assert result is mock_vectorstore

    @patch("src.graphs.routing.graph.Chroma")
    @patch("src.graphs.routing.graph.chromadb")
    @patch("src.graphs.routing.graph.OpenAIEmbeddings")
    @patch("src.graphs.routing.graph.config")
    def test_existing_collection_no_auto_create(
        self, mock_config, mock_embeddings_cls, mock_chromadb, mock_chroma_cls
    ):
        """When collection exists with documents, should NOT auto-create."""
        graph = self._setup_graph_with_mocks(mock_config, mock_chromadb)

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 25
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        mock_vectorstore = MagicMock()
        mock_chroma_cls.return_value = mock_vectorstore

        result = graph._setup_vectorstore()

        # Should NOT have called from_documents
        assert not mock_chroma_cls.from_documents.called, \
            "Should not auto-create when collection already exists"
        assert result is mock_vectorstore

    @patch("src.graphs.routing.graph.Chroma")
    @patch("src.graphs.routing.graph.chromadb")
    @patch("src.graphs.routing.graph.OpenAIEmbeddings")
    @patch("src.graphs.routing.graph.config")
    def test_returns_none_when_catalog_missing(
        self, mock_config, mock_embeddings_cls, mock_chromadb, mock_chroma_cls
    ):
        """When forza.json doesn't exist, should return None gracefully."""
        graph = _make_graph_instance()
        # Point to nonexistent directory so forza.json won't be found
        graph._get_base_path = MagicMock(return_value=Path("/nonexistent/path"))

        mock_config.vector_store.persist_directory = "./data/vector_store"
        mock_config.embedding.model = "text-embedding-3-large"
        mock_config.embedding.api_key = "test-key"
        mock_config.embedding.base_url = "https://api.openai.com/v1"

        mock_client = MagicMock()
        mock_client.get_collection.side_effect = Exception("Collection not found")
        mock_chromadb.PersistentClient.return_value = mock_client

        result = graph._setup_vectorstore()

        assert result is None

    @patch("src.graphs.routing.graph.Chroma")
    @patch("src.graphs.routing.graph.chromadb")
    @patch("src.graphs.routing.graph.OpenAIEmbeddings")
    @patch("src.graphs.routing.graph.config")
    def test_empty_collection_triggers_re_creation(
        self, mock_config, mock_embeddings_cls, mock_chromadb, mock_chroma_cls
    ):
        """When collection exists but is empty, should delete and re-create."""
        graph = self._setup_graph_with_mocks(mock_config, mock_chromadb)

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0  # Empty collection
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        mock_vectorstore = MagicMock()
        mock_chroma_cls.from_documents.return_value = mock_vectorstore

        result = graph._setup_vectorstore()

        # Should have deleted the empty collection
        mock_client.delete_collection.assert_called_once_with("forza_web_pages")
        # Should have auto-created
        assert mock_chroma_cls.from_documents.called
        assert result is mock_vectorstore
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_vectorstore_auto_init.py -v`
Expected: FAIL — `_create_documents_from_catalog` method doesn't exist yet, and `_setup_vectorstore` returns `None` on missing collection.

---

### Task 2: Implement auto-initialization

**Files:**
- Modify: `src/graphs/routing/graph.py:164-233`

- [ ] **Step 3: Add `_create_documents_from_catalog()` method**

Add this method to `RoutingGraph` class, before `_setup_vectorstore()` (before line 164):

```python
def _create_documents_from_catalog(self, catalog: dict) -> list:
    """Create LangChain Documents from forza.json catalog.

    Produces documents with all metadata fields routing nodes expect:
    title, url, url_route, category, page_id, document_type,
    sub_page_type, parent_page_id, has_parameters, parameter_count,
    url_parameters, keywords.
    """
    import json as _json
    from langchain_core.documents import Document

    documents = []
    for page in catalog.get("web_pages_catalog", []):
        metadata = page.get("metadata", {})
        structured_data = page.get("structured_data", {})

        # Build content for embedding
        content_parts = [page.get("embedding_content", "")]

        functions = structured_data.get("functions", [])
        if functions:
            content_parts.append("\n\nÖzellikler ve İşlevler:")
            content_parts.append("\n".join(f"- {func}" for func in functions))

        keywords = structured_data.get("keywords", [])
        if keywords:
            content_parts.append("\n\nAnahtar Kelimeler:")
            content_parts.append(", ".join(keywords))

        user_expressions = page.get("user_expressions", [])
        if user_expressions:
            content_parts.append("\n\nKullanıcı İfadeleri:")
            content_parts.append("\n".join(f"- {expr}" for expr in user_expressions))

        # URL parameters
        url_params = metadata.get("url_parameters", {}) or {}
        url_params_json = _json.dumps(url_params, ensure_ascii=False) if url_params else ""
        url_route = metadata.get("url_route", "")

        doc = Document(
            page_content="\n".join(content_parts),
            metadata={
                "page_id": metadata.get("page_id", ""),
                "title": metadata.get("title", ""),
                "url": url_route,
                "url_route": url_route,
                "category": metadata.get("category", ""),
                "document_type": metadata.get("page_type", "main_page"),
                "sub_page_type": metadata.get("sub_page_type", ""),
                "parent_page_id": metadata.get("parent_page_id", ""),
                "keywords": ", ".join(keywords),
                "has_parameters": len(url_params) > 0,
                "parameter_count": len(url_params),
                "url_parameters": url_params_json,
                "source": "forza_web_catalog",
                "catalog_version": catalog.get("version", "unknown"),
            },
        )
        documents.append(doc)

    return documents
```

- [ ] **Step 4: Update `_setup_vectorstore()` to auto-create on missing collection**

Replace the `_setup_vectorstore` method (lines 164-233) with:

```python
def _setup_vectorstore(self) -> Optional[Chroma]:
    """
    Initialize Chroma vectorstore for document retrieval.

    If the collection doesn't exist, auto-creates it from data/forza.json.
    Handles both dev and production (frozen exe) environments.

    Returns:
        Initialized Chroma vectorstore or None if setup fails
    """
    try:
        logger.info("[FORZA] Initializing vectorstore...")

        # Get persist directory from config, resolved relative to project root
        base_path = self._get_base_path()
        vectorstore_path = (base_path / config.vector_store.persist_directory).resolve()

        logger.debug(f"[FORZA] Vectorstore path: {vectorstore_path}")

        # Create directory if it doesn't exist
        vectorstore_path.mkdir(parents=True, exist_ok=True)

        # Setup embeddings from config
        embeddings = OpenAIEmbeddings(
            model=config.embedding.model,
            openai_api_key=config.embedding.api_key,
            base_url=config.embedding.base_url,
        )

        # Initialize Chroma client (single instance, reused for both load and create)
        chroma_settings = Settings(
            anonymized_telemetry=False,
            allow_reset=True,
            chroma_api_impl="chromadb.api.segment.SegmentAPI"
        )

        chroma_client = chromadb.PersistentClient(
            path=str(vectorstore_path),
            settings=chroma_settings
        )

        # Try to load existing collection
        try:
            collection = chroma_client.get_collection("forza_web_pages")
            doc_count = collection.count()

            if doc_count == 0:
                logger.warning("[FORZA] Collection is empty, will re-create")
                chroma_client.delete_collection("forza_web_pages")
                raise ValueError("Empty collection deleted for re-creation")

            logger.info(f"[FORZA] Collection ready - {doc_count} pages")

            vectorstore = Chroma(
                client=chroma_client,
                collection_name="forza_web_pages",
                embedding_function=embeddings,
            )

            logger.info("[FORZA] Vectorstore initialized successfully")
            return vectorstore

        except Exception as e:
            logger.warning(f"[FORZA] Collection not available: {e}")
            logger.info("[FORZA] Attempting auto-creation from forza.json...")
            return self._auto_create_collection(base_path, chroma_client, embeddings)

    except Exception as e:
        logger.error(f"[FORZA] Vectorstore initialization failed: {e}", exc_info=True)
        return None

def _auto_create_collection(self, base_path: Path, chroma_client, embeddings) -> Optional[Chroma]:
    """Auto-create forza_web_pages collection from data/forza.json.

    Uses the already-created chroma_client to avoid dual PersistentClient
    locking conflicts on the same directory.
    """
    import json as _json

    catalog_path = base_path / "data" / "forza.json"
    if not catalog_path.exists():
        logger.error(f"[FORZA] Catalog not found: {catalog_path} — cannot auto-create")
        return None

    try:
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = _json.load(f)

        documents = self._create_documents_from_catalog(catalog)
        if not documents:
            logger.error("[FORZA] No documents created from catalog")
            return None

        logger.info(f"[FORZA] Creating collection from {len(documents)} pages...")

        vectorstore = Chroma.from_documents(
            documents=documents,
            embedding=embeddings,
            collection_name="forza_web_pages",
            client=chroma_client,
        )

        logger.info(f"[FORZA] Auto-created forza_web_pages with {len(documents)} documents")
        return vectorstore

    except Exception as e:
        logger.error(f"[FORZA] Auto-creation failed: {e}", exc_info=True)
        return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_vectorstore_auto_init.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run existing tests for regression**

Run: `pytest tests/ -v --timeout=60`
Expected: No new failures.

- [ ] **Step 7: Clean up orphaned data**

```bash
rm -rf data/vector_store/065609e6-2700-4bf2-9ad3-6a6521edce4c
```

This is the orphaned HNSW data from the old ChromaDB version. The SQLite database already has 0 collections, so nothing references this data.

- [ ] **Step 8: Commit**

```bash
git add src/graphs/routing/graph.py tests/unit/test_vectorstore_auto_init.py
git commit -m "fix: auto-create forza_web_pages collection when missing from vectorstore"
```

---

## Impact Analysis

### Before (collection missing):
```
RoutingGraph.__init__()
  └── _setup_vectorstore()
      └── get_collection("forza_web_pages") → EXCEPTION
      └── return None
          └── vectorstore = None → routing silently degraded
```

### After (collection missing):
```
RoutingGraph.__init__()
  └── _setup_vectorstore()
      └── get_collection("forza_web_pages") → EXCEPTION
      └── _auto_create_collection(chroma_client)
          └── Load data/forza.json (25 pages)
          └── _create_documents_from_catalog() → 25 Documents
          └── Chroma.from_documents(client=chroma_client) → collection created (~5-10s)
      └── return vectorstore → routing works
```

### What this does NOT change:
- Graph structure (no nodes/edges modified)
- Document metadata schema (matches existing expectations from routing nodes)
- Existing working environments (collection exists → fast path, no auto-creation)
- Manual creation scripts (still work independently)
- Config structure (no new config fields)
- Graceful degradation (forza.json missing → return None, same as before)
- Single PersistentClient per directory (no dual-client conflicts)
