from unittest.mock import MagicMock, patch
import pytest


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
