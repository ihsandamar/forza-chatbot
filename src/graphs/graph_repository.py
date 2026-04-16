from src.graphs.registry import GRAPH_REGISTRY
from src.models.llm import LLM

class GraphRepository:
    def __init__(self, llm: LLM):
        self.llm = llm
        self.register_all()

    def get(self, graph_type: str):
        if isinstance(graph_type, dict):
            graph_type = graph_type.get("type") or graph_type.get("name", str(graph_type))
        if graph_type not in GRAPH_REGISTRY:
            raise ValueError(f"Graph tipi bulunamadı: {graph_type}")
        return GRAPH_REGISTRY[graph_type](self.llm).build_graph()

    def get_raw(self, graph_type: str):
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
        import logging
        logger = logging.getLogger(__name__)

        try:
            import src.graphs.chat.graph
            import src.graphs.supervisor.graph
            import src.graphs.routing.graph
            logger.info("All graphs registered: chat, supervisor, routing")
        except ImportError as e:
            logger.warning(f"Could not import graphs: {e}")
