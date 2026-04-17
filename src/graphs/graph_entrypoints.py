from src.models.llm import LLM
from src.graphs.graph_repository import GraphRepository
from src.services.config_loader import ConfigLoader

# Global config cache
_config_cache = None


def _get_config():
    global _config_cache
    if _config_cache is None:
        _config_cache = ConfigLoader.load_config()
    return _config_cache


def _make_graph(name: str):
    """Generic factory: registry'den graph oluşturur."""
    config = _get_config()
    llm = LLM(
        provider=config.llm.provider,
        model=config.llm.model,
        temperature=config.llm.temperature,
        api_key=config.llm.api_key,
    )
    repo = GraphRepository(llm=llm, app_config=config)
    return repo.get(name)


# langgraph.json entry point'leri — her biri tek satır
def supervisor_graph():
    return _make_graph("supervisor")


def routing_graph():
    return _make_graph("routing")


def report_agent_graph():
    return _make_graph("report_agent")

# Yeni agent eklendiğinde sadece bu iki satır eklenir:
# def finance_agent_graph():
#     return _make_graph("finance_agent")
