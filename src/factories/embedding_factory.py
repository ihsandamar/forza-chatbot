import logging
import os
from typing import Optional

from langchain_openai import OpenAIEmbeddings

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
            _was_already_set = "HF_HUB_OFFLINE" in os.environ
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model)
            if not _was_already_set and os.environ.get("HF_HUB_OFFLINE") == "1":
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
        return OpenAIEmbeddings(
            model=model,
            openai_api_key=api_key,
            base_url=base_url,
        )
