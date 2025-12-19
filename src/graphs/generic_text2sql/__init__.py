"""
Generic Text2SQL Graph Package.

Intent parsing for converting natural language queries to structured SQL.

Core Exports:
    - GenericText2SQLState: State definition
    - GenericText2SQLGraph: Main graph class
    - ParsedIntent, QueryStep, Filter, Aggregation, OrderBy: Data models
"""

from .state import (
    GenericText2SQLState,
    ParsedIntent,
    QueryStep,
    Filter,
    Aggregation,
    OrderBy,
)
from .graph import GenericText2SQLGraph
from .nodes import intent_parser_to_json

__all__ = [
    # State and models
    "GenericText2SQLState",
    "ParsedIntent",
    "QueryStep",
    "Filter",
    "Aggregation",
    "OrderBy",

    # Graph
    "GenericText2SQLGraph",

    # Utility functions
    "intent_parser_to_json",
]
