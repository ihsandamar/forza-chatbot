from unittest.mock import MagicMock, patch
import pytest
import sys


def test_create_sentence_transformer_returns_embedding_fn():
    mock_fn = MagicMock()
    with patch("chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction", return_value=mock_fn) as mock_st:
        from src.factories.embedding_factory import EmbeddingFactory
        result = EmbeddingFactory.create_sentence_transformer("test-model")
    assert result is mock_fn
    mock_st.assert_called_once_with(model_name="test-model")


def test_create_sentence_transformer_uses_default_model():
    with patch("chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction") as mock_st:
        mock_st.return_value = MagicMock()
        from src.factories.embedding_factory import EmbeddingFactory
        EmbeddingFactory.create_sentence_transformer()
    call_kwargs = mock_st.call_args[1]
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
    with patch("sentence_transformers.SentenceTransformer"):
        from src.factories.embedding_factory import preload_embedding_model
        assert preload_embedding_model("test-model") is True


def test_preload_embedding_model_returns_false_on_failure():
    with patch("sentence_transformers.SentenceTransformer", side_effect=Exception("no model")):
        from src.factories.embedding_factory import preload_embedding_model
        assert preload_embedding_model("test-model") is False


def test_create_sentence_transformer_preserves_existing_hf_hub_offline():
    """If HF_HUB_OFFLINE was already set before the call, it must remain set after."""
    import os

    # Mock chromadb at sys.modules level before patching
    mock_chromadb = MagicMock()
    mock_chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction = MagicMock(return_value=MagicMock())

    env_with = dict(os.environ)
    env_with["HF_HUB_OFFLINE"] = "1"

    with patch.dict(sys.modules, {"chromadb": mock_chromadb, "chromadb.utils": mock_chromadb.utils, "chromadb.utils.embedding_functions": mock_chromadb.utils.embedding_functions}):
        with patch.dict(os.environ, env_with, clear=True):
            from src.factories.embedding_factory import EmbeddingFactory
            EmbeddingFactory.create_sentence_transformer()
            # After the call, the pre-existing HF_HUB_OFFLINE should still be set
            assert os.environ.get("HF_HUB_OFFLINE") == "1", "Pre-existing HF_HUB_OFFLINE must not be deleted"


def test_create_sentence_transformer_cleans_up_hf_hub_offline_it_set():
    """If HF_HUB_OFFLINE was NOT set before the call, it must be cleaned up after."""
    import os

    # Mock chromadb at sys.modules level before patching
    mock_chromadb = MagicMock()
    mock_chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction = MagicMock(return_value=MagicMock())

    env_without = {k: v for k, v in os.environ.items() if k != "HF_HUB_OFFLINE"}

    with patch.dict(sys.modules, {"chromadb": mock_chromadb, "chromadb.utils": mock_chromadb.utils, "chromadb.utils.embedding_functions": mock_chromadb.utils.embedding_functions}):
        with patch.dict(os.environ, env_without, clear=True):
            from src.factories.embedding_factory import EmbeddingFactory
            EmbeddingFactory.create_sentence_transformer()
            # After the call, the temporary HF_HUB_OFFLINE should be removed
            assert "HF_HUB_OFFLINE" not in os.environ, "Temporarily set HF_HUB_OFFLINE must be cleaned up"
