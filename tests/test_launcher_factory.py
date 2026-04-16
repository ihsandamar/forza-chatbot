import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.llm.api_key = "sk-test"
    return cfg


def test_api_launcher_get_asgi_app_returns_fastapi(mock_config):
    """get_asgi_app() delegates to build_fastapi_app and returns the result."""
    fake_app = MagicMock()
    with patch("src.launch.api_launcher.get_config", return_value=mock_config), \
         patch("src.launch.api_launcher.build_fastapi_app", return_value=fake_app) as mock_build:
        from src.launch.api_launcher import ApiLauncher
        launcher = ApiLauncher()
        result = launcher.get_asgi_app()
        mock_build.assert_called_once_with(mock_config)
        assert result is fake_app


def test_api_launcher_run_raises_when_api_key_missing():
    """run() raises RuntimeError if api_key is absent."""
    mock_cfg = MagicMock()
    mock_cfg.llm.api_key = ""
    with patch("src.launch.api_launcher.get_config", return_value=mock_cfg):
        from src.launch.api_launcher import ApiLauncher
        launcher = ApiLauncher()
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            launcher.run()
