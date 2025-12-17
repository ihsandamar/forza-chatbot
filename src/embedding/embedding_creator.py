"""
Embedding Creator: Creates OpenAI embeddings from config
"""

from langchain_openai import OpenAIEmbeddings
from services.config_loader import ConfigLoader


class EmbeddingCreator:
    """Creates and manages OpenAI embeddings"""

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        Initialize embedding creator from config.

        Args:
            config_path: Path to configuration file
        """
        self.config = ConfigLoader.load_config(config_path)

    def create_embeddings(self) -> OpenAIEmbeddings:
        """
        Create OpenAI embeddings instance from config.

        Returns:
            Configured OpenAIEmbeddings instance
        """
        embeddings = OpenAIEmbeddings(
            model=self.config.embedding.model,
            api_key=self.config.embedding.api_key,
            base_url=self.config.embedding.base_url
        )

        return embeddings
