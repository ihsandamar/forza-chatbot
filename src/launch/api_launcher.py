# src/launch/api_launcher.py
import uvicorn
from src.core.app_config import get_config
from src.api.main import build_fastapi_app

DEFAULT_PORT = 8089


class ApiLauncher:
    """Launches the FastAPI + uvicorn server."""

    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = get_config(config_path)

    def get_asgi_app(self):
        """Return the ASGI app — used by PyInstaller / api_app.py."""
        return build_fastapi_app(self.config)

    def run(self, port: int = DEFAULT_PORT):
        """Start uvicorn. Raises RuntimeError if OPENAI_API_KEY is missing."""
        if not self.config.llm.api_key:
            raise RuntimeError(
                "OPENAI_API_KEY eksik — config/.env kontrol et"
            )
        uvicorn.run(self.get_asgi_app(), host="0.0.0.0", port=port)
