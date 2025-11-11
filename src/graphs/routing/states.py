"""
Routing Graph State.

LangGraph compatible document retrieval state.
"""

from typing import List, Tuple
from typing_extensions import TypedDict
from langchain_core.documents import Document
from langchain_core.messages import AnyMessage


class RoutingState(TypedDict, total=False):
    """
    State for routing graph - Document retrieval.

    LangGraph compatible state for document retrieval.
    """
    messages: List[AnyMessage]  # Message history (for compatibility with system)
    message: AnyMessage  # Current message to process (extracted from messages)
    related_pages: List[Tuple[Document, float]]  # List of (Document, score) tuples
