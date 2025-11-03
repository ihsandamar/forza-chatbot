"""
Type definitions for graph system.

Standardized types for all graphs:
- Message: Single message in conversation
- GraphState: Base state for all graphs
- OutputType: Enum for output types
- GraphOutput: Standardized output format

Usage:
    from src.graphs.base.graph_types import Message, GraphState, GraphOutput, OutputType

    class MyGraphState(GraphState):
        custom_field: str
        another_field: Optional[int]
"""

from typing import TypedDict, Any, List, Optional, Dict
from enum import Enum
from datetime import datetime


class MessageRole(Enum):
    """Message role in conversation."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class Message(TypedDict, total=False):
    """
    Standard message format across all graphs.

    Fields:
        role: Message sender role (user, assistant, system, tool)
        content: Message text content
        metadata: Optional metadata (timestamp, source, etc.)
    """
    role: MessageRole
    content: str
    metadata: Optional[Dict[str, Any]]


class GraphState(TypedDict, total=False):
    """
    Base state type for all graphs.

    Provides common fields that all graphs must have.
    Graphs can extend this with additional fields via subclassing.

    Fields:
        messages: Conversation message history
        session_id: Session identifier
        user_id: User identifier
        metadata: Graph-level metadata
    """
    # Core fields (all graphs must support these)
    messages: List[Message]
    session_id: str
    user_id: Optional[str]

    # Metadata
    metadata: Dict[str, Any]


class OutputType(Enum):
    """Output type from graph execution."""
    TEXT = "text"  # Plain text response
    STRUCTURED = "structured"  # Structured data (dict)
    TOOL_CALL = "tool_call"  # Tool invocation request
    ROUTING = "routing"  # Routing decision to another graph
    ERROR = "error"  # Error response


class GraphOutput(TypedDict, total=False):
    """
    Standardized output from all graphs.

    All graph outputs should conform to this structure for consistency
    and compatibility with adapters and routing systems.

    Fields:
        type: Output type (text, structured, tool_call, routing, error)
        content: Main response text
        data: Structured data (for structured output)
        next_graph: Target graph for routing
        routing_reason: Why this routing decision was made
        tool_name: Tool to invoke (for tool_call output)
        tool_args: Arguments for tool invocation
        confidence: Confidence score of the output (0.0-1.0)
        metadata: Additional metadata
    """
    type: OutputType
    content: str  # Main response

    # For structured output
    data: Optional[Dict[str, Any]]

    # For routing
    next_graph: Optional[str]
    routing_reason: Optional[str]

    # For tool calls
    tool_name: Optional[str]
    tool_args: Optional[Dict[str, Any]]

    # Confidence and metadata
    confidence: float
    metadata: Dict[str, Any]


# Type aliases for common patterns
StateDict = Dict[str, Any]
OutputDict = Dict[str, Any]
