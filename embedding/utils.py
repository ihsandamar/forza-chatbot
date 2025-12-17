from typing import Dict, Any
from embedding.models import Catalog, Page, PageMetadata, PageParameters


class EmbeddingUtils:

    @staticmethod
    def get_json_data(file_path: str):
        import json

        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data

    @staticmethod
    def json_to_model(json_data: Dict[str, Any]) -> Catalog:
        """
        Convert forza.json structure to Catalog model.

        Args:
            json_data: Raw JSON data from forza.json

        Returns:
            Catalog: Structured catalog model
        """
        pages: list[Page] = []

        for page_data in json_data.get("web_pages_catalog", []):
            # Extract metadata
            metadata_raw = page_data.get("metadata", {})

            # Parse url_parameters
            parameters: list[PageParameters] = []
            url_params = metadata_raw.get("url_parameters", {})
            for param_name, param_info in url_params.items():
                parameters.append(PageParameters(
                    name=param_name,
                    type=param_info.get("type", "string"),
                    description=param_info.get("description", ""),
                    required=param_info.get("required", False),
                    endpoint=param_info.get("endpoint", "")
                ))

            # Create metadata
            metadata = PageMetadata(
                title=metadata_raw.get("title", ""),
                url=metadata_raw.get("url_route", ""),
                category=metadata_raw.get("category", ""),
                parameters=parameters
            )

            # Extract structured data
            structured_data = page_data.get("structured_data", {})
            keywords = structured_data.get("keywords", [])

            # Create page
            page = Page(
                metadata=metadata,
                content=page_data.get("embedding_content", ""),
                user_expression=page_data.get("user_expressions", []),
                keywords=keywords
            )

            pages.append(page)

        # Create catalog
        catalog = Catalog(
            name=json_data.get("name", ""),
            version=json_data.get("version", ""),
            pages=pages
        )

        return catalog


    @staticmethod
    def load_catalog_from_file(file_path: str) -> Catalog:
        """
        Load and convert forza.json file to Catalog model.

        Args:
            file_path: Path to the forza.json file

        Returns:
            Catalog: Structured catalog model
        """
        json_data = EmbeddingUtils.get_json_data(file_path)
        catalog = EmbeddingUtils.json_to_model(json_data)
        return catalog
    

    