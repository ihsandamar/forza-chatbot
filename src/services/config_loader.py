import yaml
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

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
    def load_config(path: str = "config/config.yaml") -> Config:
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
        return Config(resolved)
