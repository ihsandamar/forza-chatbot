"""
Graph base infrastructure module.

Provides foundational classes and utilities for building graphs:
- BaseGraph: Abstract base class for all graphs
- GraphMetadata: Metadata tracking and capability definitions

Usage:
    from src.graphs.base import (
        BaseGraph,
        GraphMetadata,
        GraphCapability,
        InputSpec,
        OutputSpec,
    )
"""

from src.graphs.base.base_graph import BaseGraph
from src.graphs.base.graph_metadata import (
    GraphMetadata,
    GraphCapability,
    InputSpec,
    OutputSpec,
    create_graph_metadata
)

__all__ = [
    # Base class
    "BaseGraph",
    # Metadata
    "GraphMetadata",
    "GraphCapability",
    "InputSpec",
    "OutputSpec",
    "create_graph_metadata",
]
