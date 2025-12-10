"""
Vector Store Pipeline: Orchestrates the complete embedding pipeline
"""

from typing import Optional
from langchain_chroma import Chroma

from embedding.models import Catalog
from embedding.content_preparator import ContentPreparator
from embedding.chunker import Chunker
from embedding.embedding_creator import EmbeddingCreator
from embedding.vector_store import VectorStoreManager


class VectorStorePipeline:
    """
    Orchestrates the complete vector store creation pipeline.

    Pipeline steps:
    1. Prepare documents from catalog
    2. (Optional) Chunk documents
    3. Create embeddings
    4. Store in vector database
    """

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        Initialize pipeline with config.

        Args:
            config_path: Path to configuration file
        """
        self.config_path = config_path

        # Initialize components
        self.content_preparator = ContentPreparator()
        self.chunker = Chunker(enable_splitting=False)  # Disabled by default
        self.embedding_creator = EmbeddingCreator(config_path)
        self.vector_store_manager = VectorStoreManager(config_path)

    def run(
        self,
        catalog: Catalog,
        collection_name: str = "forza_web_pages",
        verbose: bool = True
    ) -> Chroma:
        """
        Run complete pipeline: Catalog → Vector Store.

        Args:
            catalog: Catalog model with pages
            collection_name: ChromaDB collection name
            verbose: Print progress messages

        Returns:
            Created Chroma vector store
        """
        if verbose:
            print(f">> Starting Vector Store Pipeline...")
            print(f"   Catalog: {catalog['name']} v{catalog['version']}")
            print(f"   Total pages: {len(catalog['pages'])}\n")

        # Step 1: Prepare documents
        if verbose:
            print("[1] Preparing documents from catalog...")
        documents = self.content_preparator.prepare_documents(catalog)
        if verbose:
            print(f"    Created {len(documents)} documents\n")

        # Step 2: (Optional) Chunk documents
        if verbose:
            print("[2] Chunking documents...")
        documents = self.chunker.chunk_documents(documents)
        if verbose:
            status = "enabled" if self.chunker.enable_splitting else "disabled"
            print(f"    Chunking {status}, total documents: {len(documents)}\n")

        # Step 3: Create embeddings
        if verbose:
            print("[3] Creating embeddings...")
        embeddings = self.embedding_creator.create_embeddings()
        if verbose:
            print(f"    Embedding model ready\n")

        # Step 4: Create vector store
        if verbose:
            print(f"[4] Creating vector store (collection: {collection_name})...")
            print(f"    Persist directory: {self.vector_store_manager.persist_directory}")

        vector_store = self.vector_store_manager.create_vector_store(
            documents=documents,
            embeddings=embeddings,
            collection_name=collection_name
        )

        if verbose:
            print(f"\n>> Pipeline completed successfully!")
            print(f"   Total documents embedded: {len(documents)}")
            print(f"   Location: {self.vector_store_manager.persist_directory}\n")

        return vector_store

    def load_existing(
        self,
        collection_name: str = "forza_web_pages"
    ) -> Chroma:
        """
        Load existing vector store.

        Args:
            collection_name: ChromaDB collection name

        Returns:
            Loaded Chroma vector store
        """
        embeddings = self.embedding_creator.create_embeddings()
        vector_store = self.vector_store_manager.load_vector_store(
            embeddings=embeddings,
            collection_name=collection_name
        )
        return vector_store
