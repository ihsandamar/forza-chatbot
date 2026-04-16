import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def reset_all():
    """Reset both the app_config singleton and ConfigLoader's cache before each test."""
    from src.core.app_config import reset_config
    from src.services.config_loader import ConfigLoader
    reset_config()
    ConfigLoader.clear_cache()
    yield
    reset_config()
    ConfigLoader.clear_cache()


def test_get_config_returns_same_instance():
    """get_config() is a singleton — two calls return the same object."""
    from src.core.app_config import get_config
    c1 = get_config()
    c2 = get_config()
    assert c1 is c2


def test_reset_config_clears_singleton():
    """reset_config() clears module-level singleton, forcing loader call on next get_config()."""
    from src.core.app_config import get_config, reset_config
    from src.services.config_loader import ConfigLoader

    c1 = get_config()
    reset_config()
    ConfigLoader.clear_cache()  # Clear ConfigLoader's cache to force fresh load
    c2 = get_config()
    # After reset, ConfigLoader is called again, returning a fresh object
    assert c1 is not c2


def test_get_config_loads_from_path():
    """get_config() delegates to ConfigLoader.load_config with correct path."""
    from src.core.app_config import get_config
    mock_config = MagicMock()
    with patch("src.core.app_config.ConfigLoader.load_config", return_value=mock_config) as mock_load:
        result = get_config("config/config.yaml")
        mock_load.assert_called_once_with("config/config.yaml")
        assert result is mock_config


def test_get_config_does_not_reload_on_second_call():
    """ConfigLoader is called only once even if get_config() is called many times."""
    from src.core.app_config import get_config
    mock_config = MagicMock()
    with patch("src.core.app_config.ConfigLoader.load_config", return_value=mock_config) as mock_load:
        get_config()
        get_config()
        get_config()
        assert mock_load.call_count == 1
