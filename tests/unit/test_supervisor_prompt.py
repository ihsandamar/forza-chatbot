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


def test_supervisor_graph_no_tools_import():
    """graph.py, tools modülünü import etmemeli."""
    from pathlib import Path
    src = Path("src/graphs/supervisor/graph.py").read_text(encoding="utf-8")
    assert "from src.graphs.supervisor.tools" not in src, (
        "graph.py hala tools modulunu import ediyor"
    )
    assert "SUPERVISOR_SYSTEM_PROMPT" not in src, (
        "SUPERVISOR_SYSTEM_PROMPT hala graph.py'de mevcut"
    )


def test_supervisor_all_tools_no_utility_tools():
    """build_graph() icinde get_current_time / get_supervisor_status olmamali."""
    from pathlib import Path
    src = Path("src/graphs/supervisor/graph.py").read_text(encoding="utf-8")
    assert "get_current_time" not in src, "get_current_time hala all_tools'da"
    assert "get_supervisor_status" not in src, "get_supervisor_status hala all_tools'da"
