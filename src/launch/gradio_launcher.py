# src/launch/gradio_launcher.py
from src.core.app_config import get_config
from src.launch._chat_service import build_chat_service
from src.interfaces.gradio_interface import GradioInterface


class GradioLauncher:
    """Launches the Gradio demo interface."""

    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = get_config(config_path)

    def run(self):
        chat_service = build_chat_service(self.config)
        GradioInterface(chat_service).run(server_port=7860)
