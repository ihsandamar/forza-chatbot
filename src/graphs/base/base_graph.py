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
import asyncio
from typing import Type, Optional, Dict, Any, TypeVar, Generic
from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import MemorySaver

from src.models.base_assistant_configuration import BaseAssistantConfiguration
from src.models.llm import LLM
from src.graphs.base.graph_config import GraphConfig
from src.graphs.base.graph_metadata import GraphMetadata
from src.graphs.base.graph_types import GraphState

# Generic type variable for configuration
ConfigT = TypeVar('ConfigT', bound=BaseAssistantConfiguration)


class BaseGraph(ABC, Generic[ConfigT]):
    """
    Enhanced abstract base class for all graphs with generic configuration support.

    Provides:
    - Configuration management with type safety
    - Metadata tracking
    - Type-safe state
    - Input/output validation
    - DI-compatible constructor

    Type Parameters:
        ConfigT: Configuration type (must extend BaseAssistantConfiguration)

    Subclasses must implement:
    - _get_default_metadata(): Returns GraphMetadata
    - build_graph(): Returns compiled StateGraph
    - _get_default_config(): Returns default ConfigT instance (optional)
    """

    def __init__(
        self,
        llm: LLM,
        state_class: Type[GraphState],
        config: Optional[ConfigT] = None,
        metadata: Optional[GraphMetadata] = None,
        memory: Optional[MemorySaver] = None
    ):
        """
        Initialize BaseGraph.

        Args:
            llm: Language model instance
            state_class: GraphState subclass for this graph
            config: Agent configuration instance (optional, uses _get_default_config if None)
            metadata: GraphMetadata instance (optional)
            memory: MemorySaver for state checkpointing (optional)
        """
        self.llm = llm
        self.state_class = state_class

        # Configuration
        if config is None:
            config = self._get_default_config()
        self.config = config

        # Metadata
        if metadata is None:
            metadata = self._get_default_metadata()
        self.metadata = metadata

        # Memory for checkpointing
        if memory is None:
            memory = MemorySaver()
        self.memory = memory
        self._compiled_graph = None

    def _get_default_config(self) -> ConfigT:
        """
        Return default configuration for this graph.

        Subclasses SHOULD override this to provide their specific configuration.
        Default implementation returns a basic BaseAssistantConfiguration.

        Returns:
            ConfigT instance with default configuration
        """
        return BaseAssistantConfiguration()

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
            StateGraph instance initialized with state_class and config_schema

        Note:
            config_schema enables LangGraph Dev to control and override
            configuration at runtime. The configuration type (ConfigT) is used
            as the schema, making all config fields available in LangGraph Dev.
        """
        # Get the actual configuration class type from the generic
        config_class = type(self.config)

        return StateGraph(
            state_schema=self.state_class,
            config_schema=config_class
        )

    def get_memory(self) -> MemorySaver:
        """
        Get memory object for checkpointing.

        Returns:
            MemorySaver instance
        """
        return self.memory

    def get_config(self) -> ConfigT:
        """
        Get graph configuration.

        Returns:
            ConfigT instance (agent configuration)
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
        # Try to get attribute from config
        return getattr(self.config, key, default)

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
            'config': self.config.to_dict() if hasattr(self.config, 'to_dict') else self.config.model_dump(),
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

    def _prepare_config_for_langgraph(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Prepare configuration for LangGraph runtime.

        If no config is provided, uses self.config as default.
        LangGraph Dev can override by providing config parameter.

        Args:
            config: Optional runtime config from LangGraph Dev

        Returns:
            Configuration dict ready for LangGraph
        """
        if config is None:
            config = {}

        # Add 'configurable' key with our configuration instance
        # This is the LangGraph pattern for runtime configuration
        if 'configurable' not in config:
            config['configurable'] = self.config

        return config

    def _inject_config_to_state(self, input: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Inject configuration into state for backward compatibility.

        This allows existing nodes that read from state (e.g., state.get("token"))
        to continue working while also supporting LangGraph's native config system.

        Args:
            input: Input state
            config: LangGraph config dict (may contain 'configurable')

        Returns:
            Input state with config fields injected
        """
        # Get the configuration instance (either from config or self.config)
        if config and 'configurable' in config:
            config_instance = config['configurable']
        else:
            config_instance = self.config

        # Convert to dict
        if hasattr(config_instance, 'model_dump'):
            config_dict = config_instance.model_dump()
        elif hasattr(config_instance, 'to_dict'):
            config_dict = config_instance.to_dict()
        elif hasattr(config_instance, '__dict__'):
            config_dict = config_instance.__dict__
        else:
            config_dict = {}

        # Inject config fields into state (without overwriting existing values)
        for key, value in config_dict.items():
            if key not in input:
                input[key] = value

        return input

    def _get_compiled_graph(self):
        """Return cached compiled graph, building on first call."""
        if self._compiled_graph is None:
            self._compiled_graph = self.build_graph()
        return self._compiled_graph

    # Async methods for non-blocking execution
    async def ainvoke(self, input: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Async invoke method for the graph.

        Runs the compiled graph's invoke method in an executor to avoid blocking.
        The compiled graph must have an 'invoke' method.

        Configuration is passed via LangGraph's native config system (config_schema + configurable).
        Additionally, config fields are injected into state for backward compatibility.
        LangGraph Dev can override configuration at runtime.

        Args:
            input: Input state dictionary
            config: Configuration for graph execution (optional).
                   If not provided, uses self.config as default.
                   LangGraph Dev can provide custom config here.

        Returns:
            Output from the graph
        """
        # Prepare configuration for LangGraph (adds 'configurable' key)
        config = self._prepare_config_for_langgraph(config)

        # Inject config into state for backward compatibility
        input = self._inject_config_to_state(input, config)

        compiled_graph = self._get_compiled_graph()
        loop = asyncio.get_running_loop()

        # Run blocking invoke in executor
        return await loop.run_in_executor(
            None,
            compiled_graph.invoke,
            input,
            config
        )

    async def astream(self, input: Dict[str, Any], config: Optional[Dict[str, Any]] = None):
        """
        Async stream method for the graph.

        Runs the compiled graph's stream method in an executor.
        Yields results asynchronously.

        Args:
            input: Input state dictionary
            config: Configuration for graph execution (optional)

        Yields:
            Stream results from the graph
        """
        compiled_graph = self._get_compiled_graph()
        loop = asyncio.get_running_loop()

        # Run blocking stream in executor
        for result in await loop.run_in_executor(
            None,
            compiled_graph.stream,
            input,
            config
        ):
            yield result

    def invoke(self, input: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Synchronous invoke method for the graph.

        Configuration is passed via LangGraph's native config system (config_schema + configurable).
        Additionally, config fields are injected into state for backward compatibility.
        LangGraph Dev can override configuration at runtime.

        Args:
            input: Input state dictionary
            config: Configuration for graph execution (optional).
                   If not provided, uses self.config as default.
                   LangGraph Dev can provide custom config here.

        Returns:
            Output from the graph
        """
        # Prepare configuration for LangGraph (adds 'configurable' key)
        config = self._prepare_config_for_langgraph(config)

        # Inject config into state for backward compatibility
        input = self._inject_config_to_state(input, config)

        compiled_graph = self._get_compiled_graph()
        return compiled_graph.invoke(input, config)
