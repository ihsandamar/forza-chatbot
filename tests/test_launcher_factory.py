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


# ── get_launcher ───────────────────────────────────────────────────────────────

def test_get_launcher_returns_api_launcher():
    from src.launch import get_launcher
    from src.launch.api_launcher import ApiLauncher
    with patch("src.launch.api_launcher.get_config", return_value=MagicMock()):
        launcher = get_launcher("api")
        assert isinstance(launcher, ApiLauncher)


def test_get_launcher_returns_gradio_launcher():
    from src.launch import get_launcher
    from src.launch.gradio_launcher import GradioLauncher
    with patch("src.launch.gradio_launcher.get_config", return_value=MagicMock()):
        launcher = get_launcher("gradio")
        assert isinstance(launcher, GradioLauncher)


def test_get_launcher_returns_cli_launcher():
    from src.launch import get_launcher
    from src.launch.cli_launcher import CliLauncher
    with patch("src.launch.cli_launcher.get_config", return_value=MagicMock()):
        launcher = get_launcher("cli")
        assert isinstance(launcher, CliLauncher)


def test_get_launcher_raises_on_unknown_interface():
    from src.launch import get_launcher
    with pytest.raises(ValueError, match="Bilinmeyen interface"):
        get_launcher("flask")
