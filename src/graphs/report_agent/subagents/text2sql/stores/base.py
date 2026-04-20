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
