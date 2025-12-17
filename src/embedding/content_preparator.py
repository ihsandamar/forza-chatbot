"""
Content Preparator: Converts Catalog model to LangChain Documents
"""

from typing import List
from langchain_core.documents import Document
from embedding.models import Catalog, Page


class ContentPreparator:
    """Prepares LangChain documents from Catalog model"""

    def prepare_documents(self, catalog: Catalog) -> List[Document]:
        """
        Convert catalog pages to LangChain documents.

        Args:
            catalog: Catalog model with pages

        Returns:
            List of LangChain Document objects with metadata
        """
        documents = []

        for page in catalog["pages"]:
            doc = self._page_to_document(page, catalog["version"])
            documents.append(doc)

        return documents

    def _page_to_document(self, page: Page, catalog_version: str) -> Document:
        """
        Convert a single page to a LangChain Document.

        Args:
            page: Page model
            catalog_version: Catalog version for metadata

        Returns:
            LangChain Document with rich content and metadata
        """
        metadata = page["metadata"]

        # Build comprehensive content for embedding
        content_parts = [page["content"]]

        # Add keywords as searchable content
        if page["keywords"]:
            content_parts.append("\n\nAnahtar Kelimeler:")
            content_parts.append(", ".join(page["keywords"]))

        # Add user expressions as searchable content
        if page["user_expression"]:
            content_parts.append("\n\nKullanıcı İfadeleri:")
            content_parts.append("\n".join(f"- {expr}" for expr in page["user_expression"]))

        # Add parameter information if exists
        if metadata["parameters"]:
            content_parts.append("\n\nURL Parametreleri:")
            for param in metadata["parameters"]:
                param_info = f"- {param['name']} ({param['type']}): {param['description']}"
                if param["required"]:
                    param_info += " [ZORUNLU]"
                content_parts.append(param_info)

        full_content = "\n".join(content_parts)

        # Prepare url_parameters for metadata (required by nodes)
        # ChromaDB only accepts str, int, float, bool - so convert dict to JSON string
        url_parameters_dict = {}
        if metadata["parameters"]:
            for param in metadata["parameters"]:
                url_parameters_dict[param["name"]] = {
                    "type": param["type"],
                    "description": param["description"],
                    "required": param["required"],
                    "endpoint": param["endpoint"]
                }

        # Convert to JSON string for ChromaDB compatibility
        import json
        url_parameters_json = json.dumps(url_parameters_dict, ensure_ascii=False) if url_parameters_dict else ""

        # Create document with rich metadata
        document = Document(
            page_content=full_content,
            metadata={
                "title": metadata["title"],
                "url": metadata["url"],
                "category": metadata["category"],
                "keywords": ", ".join(page["keywords"]),
                "has_parameters": len(metadata["parameters"]) > 0,
                "parameter_count": len(metadata["parameters"]),
                "url_parameters": url_parameters_json,  # JSON string for ChromaDB
                "source": "forza_catalog",
                "catalog_version": catalog_version,
            }
        )

        return document
