"""
This script creates a vector store for the Forza catalog using configurations.
It follows these steps:
1. Loading: Reading the Forza web pages catalog from JSON
2. Document Creation: Creating documents with rich metadata for each page
3. Embedding: Converting documents into vector representations using OpenAI
4. Storing: Saving vectors into ChromaDB for efficient retrieval

The script is optimized for web page search within the Forza ERP system.
"""

import json
from pathlib import Path
from typing import List, Dict, Any
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from src.services.config_loader import ConfigLoader


class ForzaCatalogVectorStore:
    """Creates and manages vector store for Forza web pages catalog"""

    def __init__(self, config_path: str = "config/config.yaml"):
        """Initialize with configuration"""
        self.config = ConfigLoader.load_config(config_path)

        # Load embedding configuration
        self.embeddings = OpenAIEmbeddings(
            model=self.config.embedding.model,
            api_key=self.config.embedding.api_key,
            base_url=self.config.embedding.base_url
        )

        # Vector store configuration
        self.persist_directory = self.config.vector_store.persist_directory

    def load_catalog(self, file_path: str) -> Dict[str, Any]:
        """Load the Forza catalog JSON file"""
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def create_documents(self, catalog: Dict[str, Any]) -> List[Document]:
        """
        Create LangChain Documents from catalog pages.
        Each web page becomes a document with rich metadata.
        """
        documents = []
        web_pages = catalog.get("web_pages_catalog", [])

        for page in web_pages:
            # Extract metadata
            metadata = page.get("metadata", {})
            structured_data = page.get("structured_data", {})

            # Create comprehensive content for embedding
            # Include main content, functions, keywords, and user expressions
            embedding_content = page.get("embedding_content", "")

            # Add structured information to content for better search
            content_parts = [embedding_content]

            # Add functions as searchable content
            functions = structured_data.get("functions", [])
            if functions:
                content_parts.append("\n\nÖzellikler ve İşlevler:")
                content_parts.append("\n".join(f"- {func}" for func in functions))

            # Add keywords as searchable content
            keywords = structured_data.get("keywords", [])
            if keywords:
                content_parts.append("\n\nAnahtar Kelimeler:")
                content_parts.append(", ".join(keywords))

            # Add user expressions as searchable content
            user_expressions = page.get("user_expressions", [])
            if user_expressions:
                content_parts.append("\n\nKullanıcı İfadeleri:")
                content_parts.append("\n".join(f"- {expr}" for expr in user_expressions))

            # Combine all content
            full_content = "\n".join(content_parts)

            # Create document with rich metadata
            doc = Document(
                page_content=full_content,
                metadata={
                    "page_id": metadata.get("page_id", ""),
                    "title": metadata.get("title", ""),
                    "url_route": metadata.get("url_route", ""),
                    "category": metadata.get("category", ""),
                    "page_type": metadata.get("page_type", ""),
                    "functions": ", ".join(functions),
                    "keywords": ", ".join(keywords),
                    "source": "forza_web_catalog",
                    "catalog_version": catalog.get("version", "unknown")
                }
            )

            documents.append(doc)

        return documents

    def create_vector_store(self, documents: List[Document], collection_name: str = "forza_web_pages"):
        """
        Create and persist vector store using ChromaDB.

        Args:
            documents: List of LangChain documents
            collection_name: Name of the ChromaDB collection
        """
        # Create persist directory if it doesn't exist
        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)

        # Create vector store
        vector_store = Chroma.from_documents(
            documents=documents,
            embedding=self.embeddings,
            collection_name=collection_name,
            persist_directory=self.persist_directory
        )

        return vector_store

    def run(self, catalog_path: str, collection_name: str = "forza_web_pages"):
        """
        Run the complete pipeline: load catalog, create documents, and store vectors.

        Args:
            catalog_path: Path to forza.json catalog file
            collection_name: Name for the ChromaDB collection
        """
        print(">> Starting Forza Catalog Vector Store Creation...")

        # Step 1: Load catalog
        print(f"\n[1] Loading catalog from: {catalog_path}")
        catalog = self.load_catalog(catalog_path)
        total_pages = catalog.get("total_pages", 0)
        version = catalog.get("version", "unknown")
        print(f"    Loaded {total_pages} pages (version: {version})")

        # Step 2: Create documents
        print("\n[2] Creating documents with metadata...")
        documents = self.create_documents(catalog)
        print(f"    Created {len(documents)} documents")

        # Print sample document info
        if documents:
            sample_doc = documents[0]
            print(f"\n    Sample Document:")
            print(f"      Title: {sample_doc.metadata['title']}")
            print(f"      Page ID: {sample_doc.metadata['page_id']}")
            print(f"      Content Length: {len(sample_doc.page_content)} characters")

        # Step 3: Create and persist vector store
        print(f"\n[3] Creating vector store (collection: {collection_name})...")
        print(f"    Embedding Model: {self.config.embedding.model}")
        print(f"    Persist Directory: {self.persist_directory}")

        vector_store = self.create_vector_store(documents, collection_name)

        print(f"\n>> Vector store created successfully!")
        print(f"   Total documents: {len(documents)}")
        print(f"   Location: {self.persist_directory}")

        return vector_store


def main():
    """Main function to run the vector store creation"""
    # Initialize
    creator = ForzaCatalogVectorStore()

    # Run the pipeline
    catalog_path = "data/forza.json"
    vector_store = creator.run(catalog_path)

    # Test the vector store with a sample query
    print("\n[TEST] Testing vector store with sample query...")
    query = "Anasayfayı göster"
    results = vector_store.similarity_search(query, k=3)

    print(f"\n[RESULTS] Top 3 results for: '{query}'")
    for i, doc in enumerate(results, 1):
        print(f"\n{i}. {doc.metadata['title']}")
        print(f"   Page ID: {doc.metadata['page_id']}")
        print(f"   URL: {doc.metadata['url_route']}")
        print(f"   Category: {doc.metadata['category']}")


if __name__ == "__main__":
    main()
