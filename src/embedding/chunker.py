"""
Chunker: Optional document splitting for large content
"""

from typing import List, Optional
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


class Chunker:
    """Splits documents into smaller chunks if needed"""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        enable_splitting: bool = False
    ):
        """
        Initialize chunker.

        Args:
            chunk_size: Maximum size of each chunk
            chunk_overlap: Overlap between chunks
            enable_splitting: Whether to enable splitting (False for now)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.enable_splitting = enable_splitting

        if enable_splitting:
            self.splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                length_function=len,
                separators=["\n\n", "\n", " ", ""]
            )
        else:
            self.splitter = None

    def chunk_documents(self, documents: List[Document]) -> List[Document]:
        """
        Split documents into chunks if enabled.

        Args:
            documents: List of LangChain documents

        Returns:
            List of documents (split or original)
        """
        if not self.enable_splitting or self.splitter is None:
            # Return original documents without splitting
            return documents

        # Split documents
        chunked_docs = self.splitter.split_documents(documents)
        return chunked_docs
