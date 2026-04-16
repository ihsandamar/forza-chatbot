import asyncio
from pathlib import Path
from src.graphs.base.base_graph import BaseGraph
from src.graphs.graph_repository import GraphRepository
from src.graphs.routing.graph import RoutingGraph
from src.graphs.supervisor.graph import create_supervisor_graph
from src.graphs.report_agent.graph import build_report_agent_graph
from src.models.llm import LLM
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

    llm = LLM(provider=config.llm.provider, model="gpt-4o-mini", temperature=0, api_key=OPENAI_API_KEY)
    repo = GraphRepository(llm=llm)
    return repo.get_raw(name)


def supervisor_graph():
    """
    Create and return the supervisor graph.

    Note: Configuration is pre-loaded by API startup event to avoid
    blocking I/O in async contexts (LangGraph detection).
    """
    config = _get_config()
    llm = LLM(provider=config.llm.provider, model=config.llm.model, temperature=config.llm.temperature, api_key=config.llm.api_key)

    return create_supervisor_graph(llm=llm)



def routing_graph() :
    """
    Create and return the routing graph.

    Note: Configuration is pre-loaded by API startup event to avoid
    blocking I/O in async contexts (LangGraph detection).
    """
    config = _get_config()
    llm = LLM(provider=config.llm.provider, model=config.llm.model, temperature=config.llm.temperature, api_key=config.llm.api_key)

    graph = RoutingGraph(llm=llm)
    return graph.build_graph()



def report_agent_graph():
    """
    Create and return the new report agent graph (report_agent redesign).

    Shared-state subgraph pattern: Text2SQL + Visualization subgraphs share
    ReportState. Native LangGraph interrupt() for HITL. Max 2 LLM calls/turn.
    """
    config = _get_config()
    llm = LLM(
        provider=config.llm.provider,
        model=config.llm.model,
        temperature=config.llm.temperature,
        api_key=config.llm.api_key,
    )

    # Paths relative to project root
    project_root = Path(__file__).parent.parent.parent
    business_rules_path = str(project_root / "src" / "graphs" / "report_agent" / "data" / "business_rules.json")
    chroma_persist_dir = str(project_root / "data" / "vector_store")

    return build_report_agent_graph(
        llm=llm.get_chat(),
        table_name="MasterReportDocumentTable",
        column_metadata={},
        connection_string=config.database.uri,
        business_rules_path=business_rules_path,
        chroma_persist_dir=chroma_persist_dir,
    )

