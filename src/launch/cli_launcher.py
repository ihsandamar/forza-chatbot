# src/launch/cli_launcher.py
import asyncio
from src.core.app_config import get_config
from src.launch._chat_service import build_chat_service
from src.interfaces.cli_interface import CLIInterface


class CliLauncher:
    """Launches the interactive CLI interface (development)."""

    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = get_config(config_path)

    def run(self):
        chat_service = build_chat_service(self.config)
        asyncio.run(CLIInterface(chat_service).run())
