from src.services.config_loader import ConfigLoader

_config = None


def get_config(path: str = "config/config.yaml"):
    """
    Return the application config singleton.
    Loads from `path` on first call; returns cached object thereafter.
    """
    global _config
    if _config is None:
        _config = ConfigLoader.load_config(path)
    return _config


def reset_config() -> None:
    """Clear the singleton — for test isolation only, not for production use."""
    global _config
    _config = None
