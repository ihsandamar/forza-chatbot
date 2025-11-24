import yaml
import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv
try:
    import aiofiles
except ImportError:
    aiofiles = None

# Global config cache to avoid repeated blocking I/O
_CONFIG_CACHE = {}

class Config:
    """
    A simple config wrapper that allows attribute access,
    and exposes llm.api_key also at the top level via instance.api_key
    """
    def __init__(self, data: dict):
        for key, val in data.items():
            if isinstance(val, dict):
                setattr(self, key, Config(val))
            else:
                setattr(self, key, val)


class ConfigLoader:
    @staticmethod
    def _get_runtime_base_path() -> Path:
        """
        Get the base path for runtime configuration files.
        When running as .exe, returns the directory where the .exe is located.
        When running as script, returns the project root.
        """
        if getattr(sys, 'frozen', False):
            # Running as compiled executable - use exe's directory
            return Path(sys.executable).parent
        else:
            # Running as script - use project root (2 levels up from this file)
            return Path(__file__).parent.parent.parent

    @staticmethod
    def clear_cache():
        """Clear the config cache. Useful for testing or reloading config."""
        global _CONFIG_CACHE
        _CONFIG_CACHE.clear()

    @staticmethod
    def load_config(path: str = "config/config.yaml") -> Config:
        """
        Load configuration from file with caching.

        Caches config to avoid repeated blocking I/O, especially important
        when called from async contexts (e.g., LangGraph).

        Args:
            path: Path to config file (relative or absolute)

        Returns:
            Config object

        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        global _CONFIG_CACHE

        # Return cached config if available
        if path in _CONFIG_CACHE:
            return _CONFIG_CACHE[path]

        # Get runtime base path
        base_path = ConfigLoader._get_runtime_base_path()

        # Load .env file from multiple possible locations
        env_locations = [
            base_path / ".env",  # Next to exe or project root
            base_path / "config" / ".env",  # In config folder
        ]

        for dotenv_path in env_locations:
            if dotenv_path.exists():
                load_dotenv(dotenv_path)
                break

        # Resolve config path relative to base path
        if Path(path).is_absolute():
            config_path = Path(path)
        else:
            config_path = base_path / path

        if not config_path.exists():
            raise FileNotFoundError(
                f"Config file not found at {config_path}\n"
                f"Base path: {base_path}\n"
                f"Running as exe: {getattr(sys, 'frozen', False)}"
            )

        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        def resolve_env_vars(value):
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_key = value[2:-1]
                return os.getenv(env_key)
            elif isinstance(value, dict):
                return {k: resolve_env_vars(v) for k, v in value.items()}
            return value

        resolved = {k: resolve_env_vars(v) for k, v in raw.items()}
        config = Config(resolved)

        # Cache for future calls
        _CONFIG_CACHE[path] = config
        return config

    @staticmethod
    async def load_config_async(path: str = "config/config.yaml") -> Config:
        """
        Async version of load_config using aiofiles for non-blocking file I/O.
        Falls back to sync version if aiofiles is not available.

        Also checks cache first to avoid unnecessary I/O.

        Args:
            path: Path to config file (relative or absolute)

        Returns:
            Config object

        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        global _CONFIG_CACHE

        # Return cached config if available
        if path in _CONFIG_CACHE:
            return _CONFIG_CACHE[path]

        # Get runtime base path
        base_path = ConfigLoader._get_runtime_base_path()

        # Load .env file from multiple possible locations
        env_locations = [
            base_path / ".env",  # Next to exe or project root
            base_path / "config" / ".env",  # In config folder
        ]

        for dotenv_path in env_locations:
            if dotenv_path.exists():
                load_dotenv(dotenv_path)
                break

        # Resolve config path relative to base path
        if Path(path).is_absolute():
            config_path = Path(path)
        else:
            config_path = base_path / path

        if not config_path.exists():
            raise FileNotFoundError(
                f"Config file not found at {config_path}\n"
                f"Base path: {base_path}\n"
                f"Running as exe: {getattr(sys, 'frozen', False)}"
            )

        # Use aiofiles if available, otherwise fall back to executor
        if aiofiles:
            async with aiofiles.open(config_path, "r", encoding="utf-8") as f:
                content = await f.read()
        else:
            # Fallback: Run sync file read in executor
            loop = asyncio.get_event_loop()
            content = await loop.run_in_executor(
                None,
                lambda: open(config_path, "r", encoding="utf-8").read()
            )

        raw = yaml.safe_load(content)

        def resolve_env_vars(value):
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_key = value[2:-1]
                return os.getenv(env_key)
            elif isinstance(value, dict):
                return {k: resolve_env_vars(v) for k, v in value.items()}
            return value

        resolved = {k: resolve_env_vars(v) for k, v in raw.items()}
        config = Config(resolved)

        # Cache for future calls
        _CONFIG_CACHE[path] = config
        return config
