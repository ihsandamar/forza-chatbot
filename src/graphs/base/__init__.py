"""
Graph base infrastructure module.

Provides foundational classes and utilities for building graphs:
- BaseGraph: Abstract base class for all graphs
- GraphConfig: Configuration management
- GraphMetadata: Metadata tracking
- Type definitions: Message, GraphState, GraphOutput, OutputType

Usage:
    from src.graphs.base import (
        BaseGraph,
        GraphConfig,
        GraphMetadata,
        GraphCapability,
        Message,
        GraphState,
        GraphOutput,
        OutputType
    )
"""

from src.graphs.base.base_graph import BaseGraph
from src.graphs.base.graph_config import GraphConfig
from src.graphs.base.graph_metadata import (
    GraphMetadata,
    GraphCapability,
    InputSpec,
    OutputSpec,
    create_graph_metadata
)
from src.graphs.base.graph_types import (
    Message,
    MessageRole,
    GraphState,
    GraphOutput,
    OutputType
)

__all__ = [
    # Base class
    "BaseGraph",
    # Configuration
    "GraphConfig",
    # Metadata
    "GraphMetadata",
    "GraphCapability",
    "InputSpec",
    "OutputSpec",
    "create_graph_metadata",
    # Types
    "Message",
    "MessageRole",
    "GraphState",
    "GraphOutput",
    "OutputType",
]
