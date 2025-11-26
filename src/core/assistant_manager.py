"""
Assistant Manager

Manage assistant configuration and behavior.
Handles runtime reconfiguration and config snapshots.
"""

from typing import Optional, List, Dict, Any
from src.core.models import AssistantConfig


class AssistantManager:
    """Manages assistant configuration."""

    def __init__(self, default_config: AssistantConfig):
        """
        Initialize assistant manager.

        Args:
            default_config: Default AssistantConfig
        """
        self.default_config = default_config
        self.current_config = default_config
        self._config_history: List[AssistantConfig] = [default_config]

    def get_config(self) -> AssistantConfig:
        """
        Get current configuration.

        Returns:
            Current AssistantConfig
        """
        return self.current_config

    def reconfigure(self, **kwargs) -> AssistantConfig:
        """
        Reconfigure assistant at runtime.

        Args:
            **kwargs: Configuration updates

        Returns:
            Updated AssistantConfig

        Raises:
            ValueError: If configuration is invalid
        """
        # Create updated config
        new_config = self.current_config.update(**kwargs)

        # Validate
        error = new_config.validate()
        if error:
            raise ValueError(f"Invalid configuration: {error}")

        # Store
        self.current_config = new_config
        self._config_history.append(new_config)

        return new_config

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Get configuration snapshot for session storage.

        Returns:
            Dictionary representation of current config
        """
        return self.current_config.to_dict()

    def revert_to_default(self) -> AssistantConfig:
        """
        Revert to default configuration.

        Returns:
            Default AssistantConfig
        """
        self.current_config = self.default_config
        self._config_history.append(self.default_config)
        return self.current_config

    def get_history(self) -> List[Dict[str, Any]]:
        """
        Get configuration change history.

        Returns:
            List of config snapshots
        """
        return [config.to_dict() for config in self._config_history]

    def get_history_count(self) -> int:
        """
        Get number of configuration changes.

        Returns:
            Number of changes
        """
        return len(self._config_history)

    def validate_update(self, **kwargs) -> Optional[str]:
        """
        Validate potential update without applying it.

        Args:
            **kwargs: Proposed configuration updates

        Returns:
            Error message if invalid, None if valid
        """
        new_config = self.current_config.update(**kwargs)
        return new_config.validate()

    def is_update_valid(self, **kwargs) -> bool:
        """
        Check if proposed update is valid.

        Args:
            **kwargs: Proposed configuration updates

        Returns:
            True if valid, False otherwise
        """
        return self.validate_update(**kwargs) is None


__all__ = ["AssistantManager"]
