"""
Configuration Management

Load and validate ChatbotConfig from environment variables or YAML files.
Supports both env vars and YAML configuration.
"""

import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
import yaml
from src.core.models import ChatbotConfig


class Config:
    """Configuration utility class."""

    @staticmethod
    def _resolve_env_vars(value: Any) -> Any:
        """
        Resolve environment variables in value.

        Supports ${VAR_NAME} format.

        Args:
            value: Value that may contain env var references

        Returns:
            Value with env vars resolved
        """
        if not isinstance(value, str):
            return value

        # Pattern for ${VAR_NAME}
        pattern = r'\$\{([^}]+)\}'

        def replace_var(match):
            var_name = match.group(1)
            return os.getenv(var_name, match.group(0))

        return re.sub(pattern, replace_var, value)

    @staticmethod
    def from_yaml(config_path: str = "config/config.yaml") -> ChatbotConfig:
        """
        Load configuration from YAML file.

        Supports environment variable substitution with ${VAR_NAME} format.

        Args:
            config_path: Path to YAML config file

        Returns:
            ChatbotConfig instance

        Raises:
            FileNotFoundError: If config file not found
            ValueError: If config is invalid
        """
        config_file = Path(config_path)

        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        # Load YAML
        with open(config_file, 'r') as f:
            yaml_config = yaml.safe_load(f)

        if not yaml_config:
            raise ValueError(f"Config file is empty: {config_path}")

        # Extract LLM configuration
        llm_config = yaml_config.get('llm', {})

        # Extract Chatbot configuration
        chatbot_config = yaml_config.get('chatbot', {})

        # Resolve environment variables
        llm_api_key = Config._resolve_env_vars(llm_config.get('api_key'))
        llm_base_url = Config._resolve_env_vars(llm_config.get('base_url'))

        # Create ChatbotConfig
        return ChatbotConfig(
            # LLM Configuration
            llm_provider=llm_config.get('provider', 'openai'),
            llm_model=llm_config.get('model', 'gpt-4o-mini'),
            llm_temperature=float(llm_config.get('temperature', 0.0)),
            llm_api_key=llm_api_key if llm_api_key and llm_api_key.startswith('sk-') else None,
            llm_base_url=llm_base_url if llm_base_url and llm_base_url.startswith('http') else None,

            # Graph Configuration
            graph_name=chatbot_config.get('graph_type', 'default'),
            graph_config={},

            # Assistant Configuration (from env or defaults)
            system_prompt=os.getenv(
                "SYSTEM_PROMPT",
                "You are a helpful assistant."
            ),
            assistant_name=os.getenv("ASSISTANT_NAME", "Assistant"),

            # Runtime Configuration
            session_timeout=int(os.getenv("SESSION_TIMEOUT", "3600")),
            max_conversation_length=int(
                os.getenv("MAX_CONVERSATION_LENGTH", "100")
            ),
            debug_mode=os.getenv("DEBUG_MODE", "false").lower() == "true",
            enable_logging=os.getenv("ENABLE_LOGGING", "true").lower() == "true"
        )

    @staticmethod
    def from_env() -> ChatbotConfig:
        """Load configuration from environment variables."""
        return ChatbotConfig(
            # LLM Configuration
            llm_provider=os.getenv("LLM_PROVIDER", "openai"),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.0")),
            llm_api_key=os.getenv("LLM_API_KEY"),
            llm_base_url=os.getenv("LLM_BASE_URL"),

            # Graph Configuration
            graph_name=os.getenv("GRAPH_NAME", "default"),
            graph_config={},

            # Assistant Configuration
            system_prompt=os.getenv(
                "SYSTEM_PROMPT",
                "You are a helpful assistant."
            ),
            assistant_name=os.getenv("ASSISTANT_NAME", "Assistant"),

            # Runtime Configuration
            session_timeout=int(os.getenv("SESSION_TIMEOUT", "3600")),
            max_conversation_length=int(
                os.getenv("MAX_CONVERSATION_LENGTH", "100")
            ),
            debug_mode=os.getenv("DEBUG_MODE", "false").lower() == "true",
            enable_logging=os.getenv("ENABLE_LOGGING", "true").lower() == "true"
        )

    @staticmethod
    def validate(config: ChatbotConfig) -> List[str]:
        """Validate configuration."""
        return config.validate()

    @staticmethod
    def is_valid(config: ChatbotConfig) -> bool:
        """Check if configuration is valid."""
        return config.is_valid()

    @staticmethod
    def print_config(config: ChatbotConfig, mask_secrets: bool = True) -> str:
        """Print configuration in readable format."""
        config_dict = config.to_dict()

        # Mask sensitive data
        if mask_secrets and config_dict.get("llm_api_key"):
            api_key = config_dict["llm_api_key"]
            config_dict["llm_api_key"] = f"{api_key[:4]}...{api_key[-4:]}"

        lines = ["=== ChatbotConfig ==="]
        for key, value in config_dict.items():
            lines.append(f"{key}: {value}")

        return "\n".join(lines)


__all__ = ["Config"]
