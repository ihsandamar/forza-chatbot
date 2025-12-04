"""
Forza Navigation Graph State.

LangGraph compatible state for web page routing with parameter extraction.
"""

from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict
from langchain_core.documents import Document
from langchain_core.messages import AnyMessage
from langgraph.graph import MessagesState


class NavigationParameter(TypedDict):
    """URL parameter definition."""
    name: str
    type: str  # "guid", "integer", "string"
    description: str
    required: bool
    default: Optional[Any]


class NavigationOutput(TypedDict):
    """Final navigation output with all required information."""
    # Basic page information
    page_id: str
    page_title: str
    url: str
    category: str

    # Sub-page information
    is_sub_page: bool
    sub_page_type: Optional[str]  # "tab", "link", None
    parent_page_id: Optional[str]
    parent_page_title: Optional[str]
    full_path: Optional[str]  # "Master Raporları > Ciro Raporu"

    # Parameters
    requires_parameters: bool
    parameters: Optional[Dict[str, NavigationParameter]]

    # Confidence and reasoning
    confidence: float
    reasoning: str

    # Display information
    suggestion_text: str
    cta_text: str  # "Sayfaya Git" or "Parametreleri Girin"

    # Alternatives
    alternative_suggestions: Optional[List[Dict[str, Any]]]


class NavigationState(MessagesState, total=False):
    """
    State management for Forza navigation graph.

    Handles document retrieval, parameter extraction, and tool execution.
    """

    # Input
    user_input: str
    """User query extracted from messages"""

    token: str
    """Authentication token for API calls"""

    # Document Retrieval
    related_pages: List[tuple]
    """List of (Document, score) tuples from similarity search"""

    most_related_document: Optional[Document]
    """Selected best matching document"""

    # Parameter Detection
    has_parameters: bool
    """Whether selected page has URL parameters"""

    # Parameter Extraction
    filled_parameters: Optional[Dict[str, Dict[str, Any]]]
    """Extracted parameters in format: {param_name: {parameter_name, value, display_name}}"""

    # Tool Results Validation
    tool_results_valid: Optional[bool]
    """Whether tool calls returned valid results"""

    # Alternative Page Finding
    tried_page_ids: Optional[set]
    """Pages already attempted (prevents loops)"""

    retry_count: Optional[int]
    """Number of alternative pages tried"""

    no_more_alternatives: Optional[bool]
    """Whether no more alternatives are available"""

    # Final Output
    navigation_output: Optional[NavigationOutput]
    """Final formatted output for frontend"""
