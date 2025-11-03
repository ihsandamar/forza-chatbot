"""
Enhanced BaseGraph with configuration and metadata support.

Extends the abstract base class with:
- Configuration management (GraphConfig)
- Metadata tracking (GraphMetadata)
- Type-safe state definitions
- Input/output validation
- Dependency injection compatibility

Usage:
    from src.graphs.base.base_graph import BaseGraph
    from src.graphs.base.graph_config import GraphConfig
    from src.graphs.base.graph_metadata import GraphMetadata
    from src.graphs.base.graph_types import GraphState
    from src.models.models import LLM

    class MyGraphState(GraphState):
        custom_field: str

    class MyGraph(BaseGraph):
        def __init__(self, llm: LLM, config: GraphConfig = None):
            super().__init__(
                llm=llm,
                state_class=MyGraphState,
                config=config,
                metadata=self._get_default_metadata()
            )

        def _get_default_metadata(self) -> GraphMetadata:
            # Return graph metadata
            pass

        def build_graph(self):
            # Build and return StateGraph
            pass
"""

from abc import ABC, abstractmethod
from typing import Type, Optional, Dict, Any
from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import MemorySaver

from src.models.models import LLM
from src.graphs.base.graph_config import GraphConfig
from src.graphs.base.graph_metadata import GraphMetadata
from src.graphs.base.graph_types import GraphState


class BaseGraph(ABC):
    """
    Enhanced abstract base class for all graphs.

    Provides:
    - Configuration management
    - Metadata tracking
    - Type-safe state
    - Input/output validation
    - DI-compatible constructor

    Subclasses must implement:
    - _get_default_metadata(): Returns GraphMetadata
    - build_graph(): Returns compiled StateGraph
    """

    def __init__(
        self,
        llm: LLM,
        state_class: Type[GraphState],
        config: Optional[GraphConfig] = None,
        metadata: Optional[GraphMetadata] = None,
        memory: Optional[MemorySaver] = None
    ):
        """
        Initialize BaseGraph.

        Args:
            llm: Language model instance
            state_class: GraphState subclass for this graph
            config: GraphConfig instance (optional)
            metadata: GraphMetadata instance (optional)
            memory: MemorySaver for state checkpointing (optional)
        """
        self.llm = llm
        self.state_class = state_class

        # Configuration
        if config is None:
            config = GraphConfig(name=self.__class__.__name__)
        self.config = config

        # Metadata
        if metadata is None:
            metadata = self._get_default_metadata()
        self.metadata = metadata

        # Memory for checkpointing
        if memory is None:
            memory = MemorySaver()
        self.memory = memory

    @abstractmethod
    def _get_default_metadata(self) -> GraphMetadata:
        """
        Return default metadata for this graph.

        Subclasses MUST implement this.

        Returns:
            GraphMetadata instance describing this graph
        """
        pass

    @abstractmethod
    def build_graph(self) -> StateGraph:
        """
        Build and return the compiled StateGraph.

        Subclasses MUST implement this.

        Returns:
            Compiled StateGraph instance
        """
        pass

    def get_graph_builder(self) -> StateGraph:
        """
        Get StateGraph builder for constructing the graph.

        Returns:
            StateGraph instance initialized with state_class
        """
        return StateGraph(self.state_class)

    def get_memory(self) -> MemorySaver:
        """
        Get memory object for checkpointing.

        Returns:
            MemorySaver instance
        """
        return self.memory

    def get_config(self) -> GraphConfig:
        """
        Get graph configuration.

        Returns:
            GraphConfig instance
        """
        return self.config

    def get_metadata(self) -> GraphMetadata:
        """
        Get graph metadata.

        Returns:
            GraphMetadata instance
        """
        return self.metadata

    def get_name(self) -> str:
        """Get graph name."""
        return self.metadata.name

    def get_category(self) -> str:
        """Get graph category."""
        return self.metadata.category

    def get_capabilities(self) -> list:
        """Get list of graph capabilities."""
        return self.metadata.get_capabilities()

    def validate_input(self, state: Dict[str, Any]) -> tuple[bool, list]:
        """
        Validate input state against input specification.

        Base implementation checks if required input field exists.
        Subclasses can override for custom validation.

        Args:
            state: State dictionary to validate

        Returns:
            Tuple of (is_valid, errors)
        """
        errors = []
        input_spec = self.metadata.input_spec

        # Check if state has the required input field
        if input_spec.required and input_spec.name not in state:
            errors.append(
                f"Required input field '{input_spec.name}' not found in state"
            )

        # Check if state is a dictionary
        if not isinstance(state, dict):
            errors.append(f"State must be a dictionary, got {type(state).__name__}")

        return len(errors) == 0, errors

    def validate_output(self, output: Dict[str, Any]) -> tuple[bool, list]:
        """
        Validate output against output specification.

        Base implementation checks if output is a dictionary.
        Subclasses can override for custom validation.

        Args:
            output: Output dictionary to validate

        Returns:
            Tuple of (is_valid, errors)
        """
        errors = []

        if not isinstance(output, dict):
            errors.append(f"Output must be a dictionary, got {type(output).__name__}")

        return len(errors) == 0, errors

    def get_config_parameter(self, key: str, default: Any = None) -> Any:
        """
        Get configuration parameter.

        Args:
            key: Parameter key
            default: Default value if not found

        Returns:
            Parameter value or default
        """
        return self.config.get_parameter(key, default)

    def get_state_class(self) -> Type[GraphState]:
        """Get state class for this graph."""
        return self.state_class

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert graph information to dictionary.

        Useful for logging and debugging.

        Returns:
            Dictionary with graph information
        """
        return {
            'name': self.get_name(),
            'category': self.get_category(),
            'capabilities': self.get_capabilities(),
            'state_class': self.state_class.__name__,
            'config': self.config.to_dict(),
            'metadata': self.metadata.to_dict()
        }

    def __str__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}({self.metadata.name})"

    def __repr__(self) -> str:
        """Detailed representation."""
        return (
            f"{self.__class__.__name__}("
            f"name={self.metadata.name}, "
            f"category={self.metadata.category}, "
            f"state_class={self.state_class.__name__}"
            f")"
        )
