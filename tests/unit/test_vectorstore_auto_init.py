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

        doc1 = documents[1]
        assert doc1.metadata["has_parameters"] is True
        assert doc1.metadata["parameter_count"] == 1
        assert doc1.metadata["url_parameters"] != ""
        params = json.loads(doc1.metadata["url_parameters"])
        assert "cari_id" in params

    def test_creates_documents_with_sub_page_metadata(self):
        """Sub-pages must have document_type, sub_page_type, parent_page_id."""
        graph = _make_graph_instance()
        documents = graph._create_documents_from_catalog(SAMPLE_CATALOG)

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

    def _setup_graph_with_mocks(self, mock_chromadb):
        """Common setup for _setup_vectorstore tests."""
        mock_config = MagicMock()
        mock_config.vector_store.persist_directory = "./data/vector_store"
        mock_config.embedding.model = "text-embedding-3-large"
        mock_config.embedding.api_key = "test-key"
        mock_config.embedding.base_url = "https://api.openai.com/v1"

        graph = _make_graph_instance()
        graph._app_config = mock_config
        # _get_base_path -> project root (test file is at tests/unit/test_*.py)
        base_path = Path(__file__).resolve().parent.parent.parent
        graph._get_base_path = MagicMock(return_value=base_path)
        return graph

    @patch("src.graphs.routing.graph.Chroma")
    @patch("src.graphs.routing.graph.chromadb")
    @patch("src.factories.embedding_factory.OpenAIEmbeddings")
    def test_auto_creates_when_collection_missing(
        self, mock_embeddings_cls, mock_chromadb, mock_chroma_cls
    ):
        """When get_collection raises, should attempt auto-creation from forza.json."""
        import tempfile, json as _json

        mock_client = MagicMock()
        mock_client.get_collection.side_effect = Exception("Collection forza_web_pages does not exist")
        mock_chromadb.PersistentClient.return_value = mock_client

        mock_vectorstore = MagicMock()
        mock_chroma_cls.from_documents.return_value = mock_vectorstore

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Write minimal forza.json so the auto-creation path is exercised
            data_dir = Path(tmp_dir) / "data"
            data_dir.mkdir()
            catalog = {"name": "Test", "version": "0.0.1", "web_pages_catalog": [
                {"metadata": {"page_id": "test", "title": "Test", "url_route": "/test",
                              "category": "Test", "page_type": "main_page"},
                 "embedding_content": "test", "structured_data": {"functions": [], "keywords": ["test"]},
                 "user_expressions": []}
            ]}
            (data_dir / "forza.json").write_text(_json.dumps(catalog), encoding="utf-8")

            graph = _make_graph_instance()
            mock_app_config = MagicMock()
            mock_app_config.vector_store.persist_directory = "./data/vector_store"
            mock_app_config.embedding.model = "text-embedding-3-large"
            mock_app_config.embedding.api_key = "test-key"
            mock_app_config.embedding.base_url = "https://api.openai.com/v1"
            graph._app_config = mock_app_config
            graph._get_base_path = MagicMock(return_value=Path(tmp_dir))

            result = graph._setup_vectorstore()

        assert mock_chroma_cls.from_documents.called, \
            "_setup_vectorstore should auto-create collection from forza.json"
        call_kwargs = mock_chroma_cls.from_documents.call_args[1]
        assert "client" in call_kwargs, "Should pass client= to from_documents"
        assert call_kwargs["client"] is mock_client
        assert result is mock_vectorstore

    @patch("src.graphs.routing.graph.Chroma")
    @patch("src.graphs.routing.graph.chromadb")
    @patch("src.factories.embedding_factory.OpenAIEmbeddings")
    def test_existing_collection_no_auto_create(
        self, mock_embeddings_cls, mock_chromadb, mock_chroma_cls
    ):
        """When collection exists with documents, should NOT auto-create."""
        graph = self._setup_graph_with_mocks(mock_chromadb)

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 25
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        mock_vectorstore = MagicMock()
        mock_chroma_cls.return_value = mock_vectorstore

        result = graph._setup_vectorstore()

        assert not mock_chroma_cls.from_documents.called, \
            "Should not auto-create when collection already exists"
        assert result is mock_vectorstore

    @patch("src.graphs.routing.graph.Chroma")
    @patch("src.graphs.routing.graph.chromadb")
    @patch("src.factories.embedding_factory.OpenAIEmbeddings")
    def test_returns_none_when_catalog_missing(
        self, mock_embeddings_cls, mock_chromadb, mock_chroma_cls
    ):
        """When forza.json doesn't exist, should return None gracefully."""
        import tempfile

        mock_client = MagicMock()
        mock_client.get_collection.side_effect = Exception("Collection not found")
        mock_chromadb.PersistentClient.return_value = mock_client

        with tempfile.TemporaryDirectory() as tmp_dir:
            graph = _make_graph_instance()
            mock_app_config = MagicMock()
            mock_app_config.vector_store.persist_directory = "./data/vector_store"
            mock_app_config.embedding.model = "text-embedding-3-large"
            mock_app_config.embedding.api_key = "test-key"
            mock_app_config.embedding.base_url = "https://api.openai.com/v1"
            graph._app_config = mock_app_config
            graph._get_base_path = MagicMock(return_value=Path(tmp_dir))

            result = graph._setup_vectorstore()

            assert result is None

    @patch("src.graphs.routing.graph.Chroma")
    @patch("src.graphs.routing.graph.chromadb")
    @patch("src.factories.embedding_factory.OpenAIEmbeddings")
    def test_empty_collection_triggers_re_creation(
        self, mock_embeddings_cls, mock_chromadb, mock_chroma_cls
    ):
        """When collection exists but is empty, should delete and re-create."""
        import tempfile, json as _json

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_client.get_collection.return_value = mock_collection
        mock_chromadb.PersistentClient.return_value = mock_client

        mock_vectorstore = MagicMock()
        mock_chroma_cls.from_documents.return_value = mock_vectorstore

        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir) / "data"
            data_dir.mkdir()
            catalog = {"name": "Test", "version": "0.0.1", "web_pages_catalog": [
                {"metadata": {"page_id": "test", "title": "Test", "url_route": "/test",
                              "category": "Test", "page_type": "main_page"},
                 "embedding_content": "test", "structured_data": {"functions": [], "keywords": ["test"]},
                 "user_expressions": []}
            ]}
            (data_dir / "forza.json").write_text(_json.dumps(catalog), encoding="utf-8")

            graph = _make_graph_instance()
            mock_app_config = MagicMock()
            mock_app_config.vector_store.persist_directory = "./data/vector_store"
            mock_app_config.embedding.model = "text-embedding-3-large"
            mock_app_config.embedding.api_key = "test-key"
            mock_app_config.embedding.base_url = "https://api.openai.com/v1"
            graph._app_config = mock_app_config
            graph._get_base_path = MagicMock(return_value=Path(tmp_dir))

            result = graph._setup_vectorstore()

        mock_client.delete_collection.assert_called_once_with("forza_web_pages")
        assert mock_chroma_cls.from_documents.called
        assert result is mock_vectorstore
