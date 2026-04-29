"""Supervisor config ve prompt testleri."""
import pytest
import importlib


def test_supervisor_model_is_mini(tmp_path):
    """Supervisor agent config gpt-4.1-mini kullanmalı."""
    import yaml
    from pathlib import Path

    config_path = Path("config/config.yaml")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    supervisor_model = cfg.get("agents", {}).get("supervisor", {}).get("model", "")
    assert supervisor_model == "gpt-4.1-mini", (
        f"Supervisor modeli 'gpt-4.1-mini' olmali, su an: {supervisor_model!r}"
    )


def test_supervisor_system_prompt_is_removed():
    """SUPERVISOR_SYSTEM_PROMPT kaldirildi — import edilememeli."""
    mod = importlib.import_module("src.graphs.supervisor.prompts")
    assert not hasattr(mod, "SUPERVISOR_SYSTEM_PROMPT"), (
        "SUPERVISOR_SYSTEM_PROMPT hala mevcut; dead code temizlenmedi."
    )


def test_tools_module_deleted():
    """tools.py silindi — import edilememeli."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.graphs.supervisor.tools")


def test_supervisor_prompt_template_renders():
    """SUPERVISOR_PROMPT_TEMPLATE dogru render edilmeli."""
    from src.graphs.supervisor.prompts import SUPERVISOR_PROMPT_TEMPLATE

    rendered = SUPERVISOR_PROMPT_TEMPLATE.format(agent_descriptions="- test_agent: test aciklama")
    assert "{agent_descriptions}" not in rendered
    assert "test_agent" in rendered


def test_supervisor_prompt_no_clarification_instruction():
    """Prompt clarification dongusu tetikleyen ifade icermemeli."""
    from src.graphs.supervisor.prompts import SUPERVISOR_PROMPT_TEMPLATE

    text = SUPERVISOR_PROMPT_TEMPLATE.lower()
    assert "netlik iste" not in text, "Clarification instruction kaldirilmadi"
    assert "belirsiz" not in text, "Clarification instruction kaldirilmadi"
