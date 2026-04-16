# src/core/app_config.py
from src.services.config_loader import ConfigLoader, Config

_config: Config | None = None


def get_config(path: str = "config/config.yaml") -> Config:
    """
    Return the application config singleton.

    On the first call, loads config from `path` via ConfigLoader and caches the
    result. All subsequent calls return the cached object regardless of `path`.

    Intended use: launchers call ``get_config(config_path)`` once at startup to
    initialise the singleton; all other code calls ``get_config()`` (no argument)
    to retrieve it.

    Args:
        path: Path to the YAML config file. Only used on the first call.

    Returns:
        The cached Config object.
    """
    global _config
    if _config is None:
        _config = ConfigLoader.load_config(path)
    return _config


def reset_config() -> None:
    """Clear the singleton cache — for test isolation only, not production use."""
    global _config
    _config = None
