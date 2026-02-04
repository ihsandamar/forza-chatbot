import asyncio
from src.graphs.base_graph import BaseGraph
from src.graphs.data_visualization.graph import build_visualization_graph
from src.graphs.generic_text2sql.graph import GenericText2SQLGraph
from src.graphs.generic_text2sql.assistant_configuration import GenericSQLAssistantConfiguration
from src.graphs.graph_repository import GraphRepository
from src.graphs.routing.graph import RoutingGraph
from src.graphs.supervisor.graph import create_supervisor_graph
from src.graphs.report.graph import build_report_graph
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



def generic_text2sql_graph() -> BaseGraph:
    """
    Create and return the generic text2sql graph.

    Note: Configuration is pre-loaded by API startup event to avoid
    blocking I/O in async contexts (LangGraph detection).
    """
    config = _get_config()
    llm = LLM(provider=config.llm.provider, model=config.llm.model, temperature=config.llm.temperature, api_key=config.llm.api_key)
    graph = GenericText2SQLGraph(llm=llm)
    return graph.build_graph()


def data_visualization_graph() -> BaseGraph:
    """
    Create and return the data visualization graph.

    Note: Configuration is pre-loaded by API startup event to avoid
    blocking I/O in async contexts (LangGraph detection).
    """
    config = _get_config()
    llm = LLM(provider=config.llm.provider, model=config.llm.model, temperature=config.llm.temperature, api_key=config.llm.api_key)

    return build_visualization_graph(llm=llm)


def report_graph():
    """
    Create and return the report graph.

    This graph orchestrates text2sql and visualization graphs to generate
    complete reports from user messages.

    Note: Configuration is pre-loaded by API startup event to avoid
    blocking I/O in async contexts (LangGraph detection).
    """
    config = _get_config()
    llm = LLM(provider=config.llm.provider, model=config.llm.model, temperature=config.llm.temperature, api_key=config.llm.api_key)

    # Create runtime configuration for GenericText2SQL
    # Empty values will be injected at runtime via RunnableConfig
    text2sql_config = GenericSQLAssistantConfiguration(
        report_name="",
        description="",
        table_name="MasterReportDocumentTable",
        query="",
        column_metadata={},
        business_rules=[]
    )

    # Build text2sql graph with runtime config and get NodeKit for merged mode
    text2sql_graph_instance = GenericText2SQLGraph(llm=llm, config=text2sql_config)
    text2sql = text2sql_graph_instance.build_graph()

    # Get NodeKit for merged Text2SQL nodes (hybrid optimization)
    text2sql_node_kit = text2sql_graph_instance.node_kit

    # Build visualization graph
    visualization = build_visualization_graph(llm=llm)

    # Build and return report graph WITH LLM for smart intent classification
    return build_report_graph(
        text2sql_graph=text2sql,
        visualization_graph=visualization,
        llm=llm,  # CRITICAL: Enable LLM-based intent classification and smart routing
        text2sql_node_kit=text2sql_node_kit,  # NodeKit for merged Text2SQL nodes
        config_schema=GenericSQLAssistantConfiguration,  # Runtime config schema for Text2SQL nodes
        enable_hitl=True,  # Enable Human-in-the-Loop features
        enable_natural_response=False,  # Disable LLM response generation, show data directly
        enable_merged_text2sql=True  # Use merged mode (hybrid optimization)
    )