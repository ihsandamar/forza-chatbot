"""
Graph configuration management.

Provides:
- GraphConfig dataclass for storing graph configuration
- YAML-based configuration loading
- Runtime parameter override support
- Configuration validation

Usage:
    from src.graphs.base.graph_config import GraphConfig

    # Load from YAML file
    config = GraphConfig.from_yaml("src/graphs/chat/config.yaml")

    # Or create programmatically
    config = GraphConfig(
        name="chat_graph",
        version="1.0.0",
        parameters={"temperature": 0.7, "max_tokens": 2000}
    )

    # Access parameters
    temp = config.parameters.get("temperature", 0.0)
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List
import os
import json

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@dataclass
class GraphConfig:
    """
    Graph-level configuration container.

    Each graph can have its own configuration file (config.yaml).
    Supports parameter override at runtime.

    Attributes:
        name: Unique graph identifier (e.g., "text2sql_graph")
        version: Configuration/graph version
        description: Human-readable description
        category: Graph category (routing, extraction, sql, rag, etc.)
        parameters: Graph-specific parameters (from YAML)
        model_overrides: Optional model preferences
        temperature: Default temperature for LLM calls
        max_tokens: Default max tokens for LLM calls
        timeout: Operation timeout in seconds
        max_retries: Maximum retry attempts
        enable_logging: Whether to log graph execution
        tags: Tags for categorization
        metadata: Additional metadata
    """

    # Identity
    name: str
    version: str = "1.0.0"
    description: str = ""
    category: str = ""

    # Parameters (from config.yaml)
    parameters: Dict[str, Any] = field(default_factory=dict)

    # LLM Configuration
    model_overrides: Optional[Dict[str, str]] = None
    temperature: float = 0.0
    max_tokens: Optional[int] = None

    # Runtime configuration
    timeout: int = 30
    max_retries: int = 3
    enable_logging: bool = True

    # Metadata
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, yaml_path: str) -> 'GraphConfig':
        """
        Load configuration from YAML file.

        Args:
            yaml_path: Path to YAML configuration file

        Returns:
            GraphConfig instance loaded from YAML

        Raises:
            FileNotFoundError: If YAML file not found
            ValueError: If YAML file is invalid
            ImportError: If yaml module not installed
        """
        if not HAS_YAML:
            raise ImportError(
                "PyYAML is required for YAML configuration loading. "
                "Install it with: pip install pyyaml"
            )

        if not os.path.exists(yaml_path):
            raise FileNotFoundError(f"Configuration file not found: {yaml_path}")

        try:
            with open(yaml_path, 'r', encoding='utf-8') as f:
                config_dict = yaml.safe_load(f)

            if config_dict is None:
                config_dict = {}

            return cls.from_dict(config_dict)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML file {yaml_path}: {str(e)}") from e
        except Exception as e:
            raise ValueError(f"Failed to load configuration from {yaml_path}: {str(e)}") from e

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'GraphConfig':
        """
        Create configuration from dictionary.

        Args:
            config_dict: Configuration dictionary

        Returns:
            GraphConfig instance
        """
        # Extract known fields
        known_fields = {
            'name', 'version', 'description', 'category',
            'model_overrides', 'temperature', 'max_tokens',
            'timeout', 'max_retries', 'enable_logging',
            'tags', 'metadata'
        }

        # Separate known fields and parameters
        config_kwargs = {}
        parameters = {}

        for key, value in config_dict.items():
            if key in known_fields:
                config_kwargs[key] = value
            elif key != 'parameters':  # Don't nest 'parameters' key
                parameters[key] = value

        # Add explicitly defined parameters
        if 'parameters' in config_dict:
            parameters.update(config_dict['parameters'])

        config_kwargs['parameters'] = parameters

        # Ensure required fields
        if 'name' not in config_kwargs:
            raise ValueError("Configuration must have 'name' field")

        return cls(**config_kwargs)

    @classmethod
    def from_yaml_relative(cls, relative_path: str) -> 'GraphConfig':
        """
        Load configuration from YAML file relative to calling module.

        Useful for graphs to load their local config.yaml file.

        Args:
            relative_path: Relative path to YAML file (e.g., "config.yaml")

        Returns:
            GraphConfig instance

        Example:
            # In src/graphs/chat/graph.py
            config = GraphConfig.from_yaml_relative("config.yaml")
        """
        import inspect
        frame = inspect.currentframe()
        caller_file = frame.f_back.f_globals['__file__']
        caller_dir = os.path.dirname(os.path.abspath(caller_file))
        yaml_path = os.path.join(caller_dir, relative_path)
        return cls.from_yaml(yaml_path)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary.

        Returns:
            Dictionary representation of configuration
        """
        return asdict(self)

    def to_yaml_string(self) -> str:
        """
        Convert configuration to YAML string.

        Returns:
            YAML string representation

        Raises:
            ImportError: If yaml module not installed
        """
        if not HAS_YAML:
            raise ImportError("PyYAML is required for YAML export")

        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)

    def to_json_string(self) -> str:
        """
        Convert configuration to JSON string.

        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), indent=2)

    def get_parameter(self, key: str, default: Any = None) -> Any:
        """
        Get a parameter value with optional default.

        Args:
            key: Parameter key
            default: Default value if key not found

        Returns:
            Parameter value or default
        """
        return self.parameters.get(key, default)

    def has_parameter(self, key: str) -> bool:
        """Check if parameter exists."""
        return key in self.parameters

    def merge_with(self, other: 'GraphConfig') -> 'GraphConfig':
        """
        Merge this config with another, prioritizing other's values.

        Args:
            other: Another GraphConfig to merge

        Returns:
            New merged GraphConfig
        """
        merged_dict = self.to_dict()
        other_dict = other.to_dict()

        # Deep merge parameters
        merged_params = merged_dict.pop('parameters', {})
        other_params = other_dict.pop('parameters', {})
        merged_params.update(other_params)

        # Merge other fields
        merged_dict.update(other_dict)
        merged_dict['parameters'] = merged_params

        return GraphConfig.from_dict(merged_dict)

    def validate(self) -> List[str]:
        """
        Validate configuration.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if not self.name:
            errors.append("Configuration must have 'name' field")

        if not isinstance(self.parameters, dict):
            errors.append("'parameters' must be a dictionary")

        if not isinstance(self.tags, list):
            errors.append("'tags' must be a list")

        if not isinstance(self.metadata, dict):
            errors.append("'metadata' must be a dictionary")

        if self.temperature < 0.0 or self.temperature > 2.0:
            errors.append("'temperature' must be between 0.0 and 2.0")

        if self.timeout <= 0:
            errors.append("'timeout' must be positive")

        if self.max_retries < 0:
            errors.append("'max_retries' must be non-negative")

        return errors

    def is_valid(self) -> bool:
        """Check if configuration is valid."""
        return len(self.validate()) == 0

    def __str__(self) -> str:
        """String representation."""
        return f"GraphConfig(name={self.name}, version={self.version}, category={self.category})"

    def __repr__(self) -> str:
        """Detailed representation."""
        return f"GraphConfig({self.to_dict()})"
