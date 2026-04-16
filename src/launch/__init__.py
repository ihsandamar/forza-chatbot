# src/launch/__init__.py
from src.launch.api_launcher import ApiLauncher
from src.launch.gradio_launcher import GradioLauncher
from src.launch.cli_launcher import CliLauncher

_LAUNCHERS = {
    "api": ApiLauncher,
    "gradio": GradioLauncher,
    "cli": CliLauncher,
}


def get_launcher(interface: str, config_path: str = "config/config.yaml"):
    """
    Return the launcher for the requested interface.

    Args:
        interface: One of "api", "gradio", "cli".
        config_path: Path to config YAML, forwarded to the launcher.

    Raises:
        ValueError: If interface is not recognised.
    """
    if interface not in _LAUNCHERS:
        raise ValueError(
            f"Bilinmeyen interface: {interface!r}. Seçenekler: {list(_LAUNCHERS)}"
        )
    return _LAUNCHERS[interface](config_path)
