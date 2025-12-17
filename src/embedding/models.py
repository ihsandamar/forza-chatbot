from typing import TypedDict


class Catalog(TypedDict):
    name: str
    version: str
    pages: list['Page']

class Page(TypedDict):
    metadata: 'PageMetadata'
    content : str
    user_expression: list[str]
    keywords: list[str]

class PageMetadata(TypedDict):
    title: str
    url: str
    category: str
    parameters: list['PageParameters']

class PageParameters(TypedDict):
    name: str  # Parameter name (e.g., "cari_id")
    type: str
    description: str
    required: bool
    endpoint: str
