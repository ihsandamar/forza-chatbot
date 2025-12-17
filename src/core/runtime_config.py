"""
Runtime Configuration - Dynamic configuration for chatbot during runtime.

KISS Principle: Simple, mutable configuration that can be updated at runtime.
SOLID Principles:
- Single Responsibility: Only manages runtime configuration
- Open/Closed: Extensible through inheritance
- Interface Segregation: Small, focused methods

Dynamic Sub-Agent Detection:
- Automatically extracts sub-agent configurations from AssistantConfiguration
- Uses Pydantic Field metadata (json_schema_extra) to identify sub-agents
- No hard-coded graph type checks needed
"""
from typing import Optional, Dict, Any, Type, TYPE_CHECKING
from dataclasses import dataclass, field, asdict
from copy import deepcopy
import os

# Import BaseAssistantConfiguration for type hints
if TYPE_CHECKING:
    from src.models.base_assistant_configuration import BaseAssistantConfiguration


@dataclass
class LLMRuntimeConfig:
    """Runtime configuration for LLM."""

    model: str = "gpt-4o-mini"
    temperature: float = 0.0
    api_key: Optional[str] = None
    provider: str = "openai"
    base_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    def update(self, **kwargs) -> 'LLMRuntimeConfig':
        """
        Update configuration with new values.

        Returns:
            New LLMRuntimeConfig instance (immutable update pattern)
        """
        current = self.to_dict()
        current.update(kwargs)
        return LLMRuntimeConfig(**current)




@dataclass
class RuntimeConfiguration:
    """
    Central runtime configuration for chatbot system.

    KISS: Simple mutable configuration with clear structure.

    Features:
    - LLM configuration (model, temperature, api_key)
    - Graph configuration (graph_type, thread_id)
    - Sub-agent configurations (routing, chat, etc)
    - Easy get/set for interface use
    - Thread-safe updates (creates new instances)

    Usage:
        # Create initial config
        config = RuntimeConfiguration(
            llm=LLMRuntimeConfig(model="gpt-4o-mini"),
            graph_type="supervisor"
        )

        # Update at runtime
        new_config = config.update_llm(model="gpt-4o")

        # Add sub-agent config
        config.add_subagent(SubAgentRuntimeConfig(
            name="routing",
            system_prompt="You are a routing assistant",
            token="secret-token"
        ))

        # Get config for UI
        ui_data = config.to_dict()
    """

    llm: LLMRuntimeConfig
    graph_type: str = "chat"
    thread_id: Optional[str] = None
    subagents: Dict[str, 'BaseAssistantConfiguration'] = field(default_factory=dict)
    extra_config: Dict[str, Any] = field(default_factory=dict)

    def update_llm(self, **kwargs) -> 'RuntimeConfiguration':
        """
        Update LLM configuration.

        Args:
            **kwargs: LLM config parameters (model, temperature, api_key, etc)

        Returns:
            New RuntimeConfiguration instance with updated LLM config

        Example:
            new_config = config.update_llm(model="gpt-4o", temperature=0.7)
        """
        new_llm = self.llm.update(**kwargs)
        return self._copy_with(llm=new_llm)

    def update_graph(self, graph_type: Optional[str] = None, thread_id: Optional[str] = None) -> 'RuntimeConfiguration':
        """
        Update graph configuration.

        Args:
            graph_type: New graph type (optional)
            thread_id: New thread ID (optional)

        Returns:
            New RuntimeConfiguration instance with updated graph config
        """
        updates = {}
        if graph_type is not None:
            updates['graph_type'] = graph_type
        if thread_id is not None:
            updates['thread_id'] = thread_id
        return self._copy_with(**updates)

    def add_subagent(self, name: str, subagent_config: 'BaseAssistantConfiguration') -> 'RuntimeConfiguration':
        """
        Add or update sub-agent configuration.

        Args:
            name: Sub-agent name (e.g., "routing", "chat")
            subagent_config: BaseAssistantConfiguration or its subclass instance

        Returns:
            New RuntimeConfiguration instance with added sub-agent

        Example:
            config = config.add_subagent(
                "routing",
                RoutingAssistantConfiguration(
                    system_prompt="You are a routing assistant",
                    token="secret-token",
                    assistant_name="RoutingAssistant"
                )
            )
        """
        new_subagents = deepcopy(self.subagents)
        new_subagents[name] = subagent_config
        return self._copy_with(subagents=new_subagents)

    def update_subagent(self, name: str, **kwargs) -> 'RuntimeConfiguration':
        """
        Update existing sub-agent configuration.

        Args:
            name: Sub-agent name
            **kwargs: Config parameters to update

        Returns:
            New RuntimeConfiguration instance with updated sub-agent

        Raises:
            KeyError: If sub-agent not found

        Example:
            config = config.update_subagent("routing", token="new-token")
        """
        if name not in self.subagents:
            raise KeyError(f"Sub-agent '{name}' not found")

        new_subagents = deepcopy(self.subagents)
        # Use Pydantic's model_copy for updating
        new_subagents[name] = self.subagents[name].model_copy(update=kwargs)
        return self._copy_with(subagents=new_subagents)

    def get_subagent(self, name: str) -> Optional['BaseAssistantConfiguration']:
        """
        Get sub-agent configuration.

        Args:
            name: Sub-agent name

        Returns:
            BaseAssistantConfiguration or None if not found
        """
        return self.subagents.get(name)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization or UI use.

        Returns:
            Dict representation of configuration
        """
        return {
            "llm": self.llm.to_dict(),
            "graph_type": self.graph_type,
            "thread_id": self.thread_id,
            "subagents": {
                name: config.model_dump()
                for name, config in self.subagents.items()
            },
            "extra_config": deepcopy(self.extra_config)
        }

    def to_builder_params(self) -> Dict[str, Any]:
        """
        Convert to parameters suitable for ChatbotBuilder.

        Returns:
            Dict with builder-compatible parameters
        """
        return {
            "model_name": self.llm.model,
            "temperature": self.llm.temperature,
            "api_key": self.llm.api_key,
            "provider": self.llm.provider,
            "base_url": self.llm.base_url,
            "graph_type": self.graph_type,
            "thread_id": self.thread_id,
        }

    def to_graph_configurable(self) -> Dict[str, Any]:
        """
        Convert to LangGraph configurable parameters.

        Returns:
            Dict with configurable parameters for graph execution
        """
        configurable = {}

        # Add thread_id if present
        if self.thread_id:
            configurable["thread_id"] = self.thread_id

        # Add sub-agent configurations
        for name, subagent in self.subagents.items():
            # Add system prompt
            if hasattr(subagent, 'system_prompt') and subagent.system_prompt:
                configurable[f"{name}_system_prompt"] = subagent.system_prompt

            # Add token if present (for RoutingAssistantConfiguration)
            if hasattr(subagent, 'token') and subagent.token:
                configurable[f"{name}_token"] = subagent.token

            # Add all other fields from the config (excluding system_prompt and assistant_name)
            config_dict = subagent.model_dump()
            for key, value in config_dict.items():
                if key not in ['system_prompt', 'assistant_name'] and value is not None:
                    configurable[f"{name}_{key}"] = value

        return configurable

    def _copy_with(self, **updates) -> 'RuntimeConfiguration':
        """
        Create a new instance with updated fields.

        Immutable update pattern for thread-safety.

        Args:
            **updates: Fields to update

        Returns:
            New RuntimeConfiguration instance
        """
        current = {
            "llm": self.llm,
            "graph_type": self.graph_type,
            "thread_id": self.thread_id,
            "subagents": deepcopy(self.subagents),
            "extra_config": deepcopy(self.extra_config)
        }
        current.update(updates)
        return RuntimeConfiguration(**current)

    @classmethod
    def from_config_loader(cls, config, graph_type: Optional[str] = None, thread_id: Optional[str] = None) -> 'RuntimeConfiguration':
        """
        Create RuntimeConfiguration from ConfigLoader config.

        Args:
            config: Config object from ConfigLoader
            graph_type: Override graph type (optional)
            thread_id: Thread ID for session management (optional)

        Returns:
            RuntimeConfiguration instance
        """
        llm_config = LLMRuntimeConfig(
            model=config.llm.model,
            temperature=config.llm.temperature,
            api_key=config.llm.api_key,
            provider=getattr(config.llm, 'provider', 'openai'),
            base_url=getattr(config.llm, 'base_url', None)
        )

        return cls(
            llm=llm_config,
            graph_type=graph_type or config.chatbot.graph_type,
            thread_id=thread_id
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RuntimeConfiguration':
        """
        Create RuntimeConfiguration from dictionary.

        Note: This method does not reconstruct sub-agents from the dictionary
        because we cannot determine which specific configuration class to use
        (RoutingAssistantConfiguration, ChatAssistantConfiguration, etc.).
        Sub-agents should be added manually using add_subagent() after creation,
        or use from_config_with_assistant() for automatic sub-agent detection.

        Args:
            data: Dictionary with configuration data

        Returns:
            RuntimeConfiguration instance (without sub-agents)
        """
        llm_data = data.get("llm", {})
        llm_config = LLMRuntimeConfig(**llm_data)

        return cls(
            llm=llm_config,
            graph_type=data.get("graph_type", "chat"),
            thread_id=data.get("thread_id"),
            subagents={},  # Sub-agents not reconstructed from dict
            extra_config=deepcopy(data.get("extra_config", {}))
        )

    @classmethod
    def extract_subagents_from_assistant_config(
        cls,
        assistant_config_instance: Any
    ) -> Dict[str, 'BaseAssistantConfiguration']:
        """
        Extract sub-agent configurations from AssistantConfiguration using helper methods.

        This method uses the get_*_config() helper methods pattern in AssistantConfiguration
        classes (e.g., get_routing_config(), get_chat_config()) to extract typed configurations.

        Args:
            assistant_config_instance: AssistantConfiguration instance (e.g., SupervisorAssistantConfiguration)

        Returns:
            Dictionary of BaseAssistantConfiguration (or subclasses) keyed by agent name

        Example:
            # Automatically detect routing and chat agents from SupervisorAssistantConfiguration
            supervisor_config = SupervisorAssistantConfiguration()
            subagents = RuntimeConfiguration.extract_subagents_from_assistant_config(
                supervisor_config
            )
            # Returns: {"routing": RoutingAssistantConfiguration(...), "chat": ChatAssistantConfiguration(...)}
        """
        subagents: Dict[str, 'BaseAssistantConfiguration'] = {}

        # Find all get_*_config() methods
        for attr_name in dir(assistant_config_instance):
            if attr_name.startswith('get_') and attr_name.endswith('_config'):
                # Extract agent name: get_routing_config -> routing
                agent_name = attr_name[4:-7]  # Remove 'get_' and '_config'

                # Get the method
                method = getattr(assistant_config_instance, attr_name)

                # Call it if it's callable
                if callable(method):
                    try:
                        config = method()
                        # Verify it's a BaseAssistantConfiguration
                        from src.models.base_assistant_configuration import BaseAssistantConfiguration
                        if isinstance(config, BaseAssistantConfiguration):
                            subagents[agent_name] = config
                    except Exception as e:
                        # Skip methods that fail
                        print(f"Warning: Could not extract {agent_name} config: {e}")

        return subagents

    @classmethod
    def from_config_with_assistant(
        cls,
        config,
        assistant_config_instance: Optional[Any] = None,
        graph_type: Optional[str] = None,
        thread_id: Optional[str] = None
    ) -> 'RuntimeConfiguration':
        """
        Create RuntimeConfiguration with automatic sub-agent detection.

        This method combines config loader data with dynamic sub-agent extraction
        from AssistantConfiguration, eliminating need for hard-coded graph checks.

        Args:
            config: Config object from ConfigLoader
            assistant_config_instance: Optional AssistantConfiguration instance with values
            graph_type: Override graph type (optional)
            thread_id: Thread ID for session management (optional)

        Returns:
            RuntimeConfiguration with automatically detected sub-agents

        Example:
            # Automatic sub-agent detection
            from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration

            supervisor_config = SupervisorAssistantConfiguration()
            runtime_config = RuntimeConfiguration.from_config_with_assistant(
                config=loaded_config,
                assistant_config_instance=supervisor_config,
                graph_type="supervisor"
            )
            # Automatically includes routing and chat sub-agents!
        """
        llm_config = LLMRuntimeConfig(
            model=config.llm.model,
            temperature=config.llm.temperature,
            api_key=config.llm.api_key,
            provider=getattr(config.llm, 'provider', 'openai'),
            base_url=getattr(config.llm, 'base_url', None)
        )

        runtime_config = cls(
            llm=llm_config,
            graph_type=graph_type or config.chatbot.graph_type,
            thread_id=thread_id
        )

        # Dynamically extract sub-agents if assistant_config_instance provided
        if assistant_config_instance:
            subagents = cls.extract_subagents_from_assistant_config(
                assistant_config_instance
            )

            # Add all detected sub-agents
            for agent_name, subagent_config in subagents.items():
                runtime_config = runtime_config.add_subagent(agent_name, subagent_config)

        return runtime_config


__all__ = ["RuntimeConfiguration", "LLMRuntimeConfig"]
