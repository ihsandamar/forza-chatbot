"""Supervisor config ve prompt testleri."""
import pytest


def test_supervisor_model_is_mini(tmp_path):
    """Supervisor agent config gpt-4.1-mini kullanmalı."""
    import yaml
    from pathlib import Path

    config_path = Path("config/config.yaml")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    supervisor_model = cfg.get("agents", {}).get("supervisor", {}).get("model", "")
    assert supervisor_model == "gpt-4.1-mini", (
        f"Supervisor modeli 'gpt-4.1-mini' olmalı, şu an: {supervisor_model!r}"
    )
