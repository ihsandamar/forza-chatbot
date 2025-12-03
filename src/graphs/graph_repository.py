from src.graphs.registry import GRAPH_REGISTRY
from src.models.llm import LLM

class GraphRepository:
    def __init__(self, llm: LLM):
        self.llm = llm
        self.register_all()  # Register all graphs on initialization

    def get(self, graph_type: str):
        # Handle case where graph_type might be a dict (extract type if it is)
        if isinstance(graph_type, dict):
            graph_type = graph_type.get("type") or graph_type.get("name", str(graph_type))

        if graph_type not in GRAPH_REGISTRY:
            raise ValueError(f"Graph tipi bulunamadı: {graph_type}")
        return GRAPH_REGISTRY[graph_type](self.llm).build_graph()

    def get_raw(self, graph_type: str):
        # Handle case where graph_type might be a dict (extract type if it is)
        if isinstance(graph_type, dict):
            graph_type = graph_type.get("type") or graph_type.get("name", str(graph_type))

        if graph_type not in GRAPH_REGISTRY:
            raise ValueError(f"Graph tipi bulunamadı: {graph_type}")
        return GRAPH_REGISTRY[graph_type](self.llm)

    def list_graphs(self):
        return list(GRAPH_REGISTRY.keys())
    
    def register_all(self):
        """
        Registers all graph modules.
        Uses explicit imports to ensure PyInstaller compatibility.
        """
        # Explicit imports for PyInstaller compatibility
        import logging
        logger = logging.getLogger(__name__)

        # New modular graph structure (active)
        try:
            import src.graphs.chat.graph
            import src.graphs.supervisor.graph
            import src.graphs.routing.graph

            logger.info("ChatGraph registered")
        except ImportError as e:
            logger.warning(f"Could not import ChatGraph: {e}")

        try:
            import src.graphs.routing.graph
            logger.info("RoutingGraph registered")
        except ImportError as e:
            logger.warning(f"Could not import RoutingGraph: {e}")

        try:
            import src.graphs.forza_routing_graph
            logger.info("ForzaRoutingGraph registered")
        except ImportError as e:
            logger.warning(f"Could not import ForzaRoutingGraph: {e}")

        # TODO: Legacy graphs have been removed and need to be refactored
        # The following graphs were marked for deletion and should be reimplemented as needed:
        # - text2sql_graph
        # - core_text2sql_graph
        # - generic_sql_graph
        # - enhanced_query_extraction_graph_old
        # - forza_rag_graph
        # - forza_toolkit_graph
        # - gib_mevzuat_graph
        # - graph
        # - query_extraction_graph
        # - intent_graph
        # - main_graph_with_tools
        # - master_report_graph
        # - sefim_rag_graph
        # - supervisor_graph
    

