from src.graphs.registry import GRAPH_REGISTRY
from src.models.models import LLM

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
        try:
            # New modular graph structure
            import src.graphs.chat.graph

            # Legacy graphs (to be refactored)
            import src.graphs.text2sql_graph
            import src.graphs.core_text2sql_graph
            import src.graphs.generic_sql_graph
            import src.graphs.enhanced_query_extraction_graph_old
            import src.graphs.forza_rag_graph
            import src.graphs.forza_routing_graph
            import src.graphs.forza_toolkit_graph
            import src.graphs.gib_mevzuat_graph
            import src.graphs.graph
            import src.graphs.query_extraction_graph
            import src.graphs.intent_graph
            import src.graphs.main_graph_with_tools
            import src.graphs.master_report_graph
            import src.graphs.sefim_rag_graph
            import src.graphs.supervisor_graph
        except ImportError as e:
            # Log but don't fail - some graphs may have optional dependencies
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not import graph module: {e}")
    

