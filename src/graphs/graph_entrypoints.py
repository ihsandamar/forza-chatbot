import asyncio
from src.graphs.base_graph import BaseGraph
from src.graphs.graph_repository import GraphRepository
from src.graphs.supervisor.graph import create_supervisor_graph
from src.models.models import LLM
from src.services.config_loader import ConfigLoader


# TODO: Add Dynamic Module Discovery and Loading

# Global config cache to avoid repeated blocking I/O
_config_cache = None


def _get_config():
    """
    Get cached config or load it synchronously.

    Uses global cache to avoid repeated blocking I/O. If config is already cached,
    returns immediately without any I/O.
    """
    global _config_cache
    if _config_cache is None:
        _config_cache = ConfigLoader.load_config()
    return _config_cache


def _get_config_no_block():
    """
    Get cached config without blocking. Returns None if not yet loaded.

    Used by sync functions called from async contexts to avoid blocking detection.
    """
    global _config_cache
    return _config_cache


def graph(name: str) -> BaseGraph:
    """
    Returns a graph object based on the specified name.

    :param name: Name of the graph
    :return: Graph object
    :rtype: MainGraph
    """

    # Get config - will be pre-cached by API startup event or lazy-loaded on first sync call
    config = _get_config()
    OPENAI_API_KEY = config.llm.api_key

    llm = LLM(model="gpt-4o-mini", temperature=0, api_key=OPENAI_API_KEY)
    repo = GraphRepository(llm=llm)
    return repo.get_raw(name)


def supervisor_graph():
    """
    Create and return the supervisor graph.

    Note: Configuration is pre-loaded by API startup event to avoid
    blocking I/O in async contexts (LangGraph detection).
    """
    config = _get_config()
    llm = LLM(model=config.llm.model, temperature=config.llm.temperature, api_key=config.llm.api_key)

    return create_supervisor_graph(llm=llm)