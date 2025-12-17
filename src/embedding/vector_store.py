"""
Vector Store Manager: ChromaDB operations
"""

from typing import List
from pathlib import Path
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from services.config_loader import ConfigLoader


class VectorStoreManager:
    """Manages ChromaDB vector store operations"""

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        Initialize vector store manager.

        Args:
            config_path: Path to configuration file
        """
        self.config = ConfigLoader.load_config(config_path)
        self.persist_directory = self.config.vector_store.persist_directory

    def create_vector_store(
        self,
        documents: List[Document],
        embeddings: OpenAIEmbeddings,
        collection_name: str = "forza_web_pages"
    ) -> Chroma:
        """
        Create and persist vector store.

        Args:
            documents: List of LangChain documents
            embeddings: OpenAI embeddings instance
            collection_name: ChromaDB collection name

        Returns:
            Chroma vector store instance
        """
        # Create persist directory if needed
        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)

        # Create vector store
        vector_store = Chroma.from_documents(
            documents=documents,
            embedding=embeddings,
            collection_name=collection_name,
            persist_directory=self.persist_directory
        )

        return vector_store

    def load_vector_store(
        self,
        embeddings: OpenAIEmbeddings,
        collection_name: str = "forza_web_pages"
    ) -> Chroma:
        """
        Load existing vector store.

        Args:
            embeddings: OpenAI embeddings instance
            collection_name: ChromaDB collection name

        Returns:
            Loaded Chroma vector store instance
        """
        vector_store = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=self.persist_directory
        )

        return vector_store
