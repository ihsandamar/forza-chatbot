"""
Graph metadata system.

Provides metadata tracking for graphs:
- GraphCapability: Enum of graph capabilities
- InputSpec: Input specification
- OutputSpec: Output specification
- GraphMetadata: Complete metadata container

Usage:
    from src.graphs.base.graph_metadata import (
        GraphMetadata, GraphCapability, InputSpec, OutputSpec
    )

    metadata = GraphMetadata(
        name="text2sql_graph",
        category="sql",
        capabilities=[GraphCapability.SQL_GENERATION],
        input_spec=InputSpec(name="messages", type="list[dict]"),
        output_spec=OutputSpec(name="result", type="dict"),
        version="1.0.0"
    )
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
from datetime import datetime


class GraphCapability(Enum):
    """
    Enum of graph capabilities.

    Used to categorize what a graph can do, enabling
    capability-based selection and discovery.
    """
    # Text processing
    TEXT_GENERATION = "text_generation"
    TEXT_UNDERSTANDING = "text_understanding"
    TEXT_CLASSIFICATION = "text_classification"

    # Intent & Entity
    INTENT_DETECTION = "intent_detection"
    ENTITY_EXTRACTION = "entity_extraction"

    # Query processing
    QUERY_EXTRACTION = "query_extraction"
    QUERY_PARSING = "query_parsing"

    # SQL operations
    SQL_GENERATION = "sql_generation"
    SQL_VALIDATION = "sql_validation"

    # Retrieval & RAG
    RAG = "rag"
    RETRIEVAL = "retrieval"
    RANKING = "ranking"

    # Routing & orchestration
    ROUTING = "routing"
    ORCHESTRATION = "orchestration"
    DECISION_MAKING = "decision_making"

    # Tool operations
    TOOL_USE = "tool_use"
    TOOL_SELECTION = "tool_selection"

    # Reporting & formatting
    REPORTING = "reporting"
    FORMATTING = "formatting"
    SUMMARIZATION = "summarization"

    # Other
    VALIDATION = "validation"
    CACHING = "caching"


@dataclass
class InputSpec:
    """
    Input specification for graph.

    Describes what input a graph expects.

    Attributes:
        name: Field name in state
        type: Type description (e.g., "list[dict]", "str", "dict")
        required: Whether this input is required
        description: Human-readable description
    """
    name: str
    type: str
    required: bool = True
    description: str = ""

    def __str__(self) -> str:
        """String representation."""
        return f"{self.name}: {self.type}" + (" (required)" if self.required else " (optional)")


@dataclass
class OutputSpec:
    """
    Output specification for graph.

    Describes what output a graph produces.

    Attributes:
        name: Output field name
        type: Type description (e.g., "str", "dict", "list[dict]")
        description: Human-readable description
    """
    name: str
    type: str
    description: str = ""

    def __str__(self) -> str:
        """String representation."""
        return f"{self.name}: {self.type}"


@dataclass
class GraphMetadata:
    """
    Complete metadata about a graph.

    Provides comprehensive information about graph capabilities,
    requirements, input/output specifications, and other metadata.

    This helps with:
    - Graph discovery and selection
    - Type checking and validation
    - Documentation generation
    - Capability checking before execution
    - Performance monitoring

    Attributes:
        name: Unique graph identifier
        category: Graph category (routing, extraction, sql, rag, etc.)
        capabilities: List of capabilities this graph has
        input_spec: Input specification
        output_spec: Output specification
        required_tools: List of required tools
        required_models: List of required models
        version: Graph version
        author: Author/maintainer
        last_updated: Last update timestamp
        tags: Tags for categorization
        source_file: Source file path
        dependencies: External dependencies
    """

    # Identity
    name: str
    category: str

    # Core specifications
    capabilities: List[GraphCapability]
    input_spec: InputSpec
    output_spec: OutputSpec

    # Requirements
    required_tools: List[str] = field(default_factory=list)
    required_models: List[str] = field(default_factory=list)

    # Versioning & authorship
    version: str = "1.0.0"
    author: str = ""
    last_updated: str = ""

    # Tags & metadata
    tags: List[str] = field(default_factory=list)
    source_file: str = ""
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_capability(self, capability: GraphCapability) -> bool:
        """
        Check if graph has specific capability.

        Args:
            capability: Capability to check

        Returns:
            True if graph has capability
        """
        return capability in self.capabilities

    def has_any_capability(self, capabilities: List[GraphCapability]) -> bool:
        """
        Check if graph has any of the specified capabilities.

        Args:
            capabilities: List of capabilities to check

        Returns:
            True if graph has any of the capabilities
        """
        return any(self.has_capability(cap) for cap in capabilities)

    def has_all_capabilities(self, capabilities: List[GraphCapability]) -> bool:
        """
        Check if graph has all specified capabilities.

        Args:
            capabilities: List of capabilities to check

        Returns:
            True if graph has all capabilities
        """
        return all(self.has_capability(cap) for cap in capabilities)

    def get_capabilities(self) -> List[str]:
        """
        Get list of capability names.

        Returns:
            List of capability names (strings)
        """
        return [cap.value for cap in self.capabilities]

    def get_required_tools(self) -> List[str]:
        """Get list of required tools."""
        return self.required_tools.copy()

    def get_required_models(self) -> List[str]:
        """Get list of required models."""
        return self.required_models.copy()

    def matches_requirements(
        self,
        available_tools: List[str],
        available_models: List[str]
    ) -> tuple[bool, List[str]]:
        """
        Check if graph's requirements are met.

        Args:
            available_tools: List of available tools
            available_models: List of available models

        Returns:
            Tuple of (is_match, missing_requirements)
        """
        missing = []

        for tool in self.required_tools:
            if tool not in available_tools:
                missing.append(f"Tool: {tool}")

        for model in self.required_models:
            if model not in available_models:
                missing.append(f"Model: {model}")

        return len(missing) == 0, missing

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary representation.

        Returns:
            Dictionary with metadata
        """
        return {
            'name': self.name,
            'category': self.category,
            'capabilities': self.get_capabilities(),
            'input_spec': {
                'name': self.input_spec.name,
                'type': self.input_spec.type,
                'required': self.input_spec.required,
                'description': self.input_spec.description
            },
            'output_spec': {
                'name': self.output_spec.name,
                'type': self.output_spec.type,
                'description': self.output_spec.description
            },
            'required_tools': self.required_tools,
            'required_models': self.required_models,
            'version': self.version,
            'author': self.author,
            'last_updated': self.last_updated,
            'tags': self.tags,
            'source_file': self.source_file,
            'dependencies': self.dependencies,
            'metadata': self.metadata
        }

    def __str__(self) -> str:
        """String representation."""
        caps = ', '.join(self.get_capabilities())
        return f"GraphMetadata({self.name}, category={self.category}, capabilities=[{caps}])"

    def __repr__(self) -> str:
        """Detailed representation."""
        return f"GraphMetadata({self.to_dict()})"


# Helper functions for creating metadata

def create_graph_metadata(
    name: str,
    category: str,
    capabilities: List[GraphCapability],
    input_type: str = "list[dict]",
    output_type: str = "dict",
    **kwargs
) -> GraphMetadata:
    """
    Create GraphMetadata with sensible defaults.

    Args:
        name: Graph name
        category: Graph category
        capabilities: List of capabilities
        input_type: Input type description
        output_type: Output type description
        **kwargs: Additional metadata fields

    Returns:
        GraphMetadata instance
    """
    return GraphMetadata(
        name=name,
        category=category,
        capabilities=capabilities,
        input_spec=InputSpec(
            name="messages",
            type=input_type,
            description=kwargs.pop("input_description", "")
        ),
        output_spec=OutputSpec(
            name="result",
            type=output_type,
            description=kwargs.pop("output_description", "")
        ),
        **kwargs
    )
