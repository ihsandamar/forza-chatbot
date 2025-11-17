"""
Routing Graph Implementation.

Simple document retrieval graph for page navigation.
"""

import logging
from typing import Optional
from pathlib import Path
import sys

from langgraph.graph import StateGraph, START, END
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
import chromadb
from chromadb.config import Settings

from src.models.llm import LLM
from src.graphs.base.base_graph import BaseGraph
from src.graphs.base.graph_config import GraphConfig
from src.graphs.base.graph_metadata import (
    GraphMetadata,
    GraphCapability,
    InputSpec,
    OutputSpec,
)
from src.graphs.registry import register_graph
from src.services.config_loader import ConfigLoader

from .states import RoutingState
from .nodes import normalize_messages_to_message, document_retrieval_node

logger = logging.getLogger(__name__)
config = ConfigLoader.load_config("config/config.yaml")


@register_graph("routing")
class RoutingGraph(BaseGraph):
    """
    Simple routing graph for document retrieval.

    Single node architecture:
    START → document_retrieval → END
    """

    def __init__(
        self,
        llm: LLM,
        config: Optional[GraphConfig] = None
    ):
        """
        Initialize RoutingGraph.

        Args:
            llm: Language model instance
            config: GraphConfig instance (optional)
        """
        if config is None:
            try:
                config = GraphConfig.from_yaml("src/graphs/routing/config.yaml")
            except FileNotFoundError:
                config = GraphConfig(name="routing")

        super().__init__(
            llm=llm,
            state_class=RoutingState,
            config=config,
            metadata=self._get_default_metadata(),
        )

        self.vectorstore = self._setup_vectorstore()

    def _get_default_metadata(self) -> GraphMetadata:
        """Return default metadata for routing graph."""
        return GraphMetadata(
            name="routing",
            category="navigation",
            capabilities=[
                GraphCapability.TEXT_UNDERSTANDING,
            ],
            input_spec=InputSpec(
                name="message",
                type="AnyMessage",
                description="Current user message to process",
            ),
            output_spec=OutputSpec(
                name="related_pages",
                type="list[tuple]",
                description="Retrieved documents with relevance scores",
            ),
            version="1.0.0",
            tags=[
                "routing",
                "navigation",
                "document-retrieval",
                "langgraph-compatible",
            ],
        )

    def _setup_vectorstore(self) -> Optional[Chroma]:
        """Initialize vectorstore for document retrieval."""
        try:
            logger.info("[ROUTING] Setting up vectorstore...")

            # Get base path (works for both dev and exe)
            # Path: src/graphs/routing/graph.py -> need to go up to project root
            is_frozen = getattr(sys, 'frozen', False)
            if is_frozen:
                base_path = Path(sys.executable).parent
                logger.debug("[ROUTING] Running as exe")
            else:
                # graph.py is at: forza-chatbot/src/graphs/routing/graph.py
                # Need to go up 4 levels: routing -> graphs -> src -> forza-chatbot (root)
                base_path = Path(__file__).resolve().parent.parent.parent.parent
                logger.debug("[ROUTING] Running as script")

            vectorstore_path = base_path / "data" / "vector_index" / "vegaforza_chroma_db"

            logger.info(f"[ROUTING] Base path: {base_path}")
            logger.info(f"[ROUTING] Vectorstore path: {vectorstore_path}")
            logger.info(f"[ROUTING] Path exists: {vectorstore_path.exists()}")

            if not vectorstore_path.exists():
                logger.error(f"[ROUTING] Vectorstore path NOT FOUND: {vectorstore_path}")
                # Try to find data folder
                data_path = base_path / "data"
                if data_path.exists():
                    logger.info(f"[ROUTING] Data folder exists at: {data_path}")
                    logger.info(f"[ROUTING] Contents: {list(data_path.iterdir())[:10]}")
                else:
                    logger.error(f"[ROUTING] Data folder not found at: {data_path}")
                return None

            # Setup embeddings
            embeddings = OpenAIEmbeddings(
                model="text-embedding-3-small",
                openai_api_key=config.llm.api_key,
                base_url=config.llm.base_url,
            )

            # Setup Chroma client
            chroma_settings = Settings(
                anonymized_telemetry=False,
                allow_reset=True,
                chroma_api_impl="chromadb.api.segment.SegmentAPI"
            )

            chroma_client = chromadb.PersistentClient(
                path=str(vectorstore_path),
                settings=chroma_settings
            )

            # List available collections
            try:
                collections = chroma_client.list_collections()
                logger.info(f"[ROUTING] Available collections: {[c.name for c in collections]}")
            except Exception as e:
                logger.debug(f"[ROUTING] Could not list collections: {e}")

            # Get collection
            try:
                collection = chroma_client.get_collection("vegaforza_web_pages")
                count = collection.count()
                logger.info(f"[ROUTING] Collection 'vegaforza_web_pages' found with {count} documents")

                if count == 0:
                    logger.warning("[ROUTING] Collection is empty!")
                    return None
            except Exception as e:
                logger.error(f"[ROUTING] Could not get collection: {e}")
                logger.error("[ROUTING] Available collections listed above")
                return None

            # Create vectorstore
            vectorstore = Chroma(
                client=chroma_client,
                collection_name="vegaforza_web_pages",
                embedding_function=embeddings,
            )

            logger.info(f"[ROUTING] Vectorstore ready - {count} documents")
            return vectorstore

        except Exception as e:
            logger.error(f"[ROUTING] Vectorstore setup failed: {e}", exc_info=True)
            return None

    def build_graph(self) -> StateGraph:
        """
        Build and return the compiled StateGraph.

        Two-node architecture:
        START → normalize_messages → document_retrieval → END

        Returns:
            Compiled StateGraph instance
        """
        builder = self.get_graph_builder()

        logger.info(f"[ROUTING] Building graph - Vectorstore: {self.vectorstore is not None}")

        # Node 1: Normalize messages to single message
        builder.add_node("normalize_messages", normalize_messages_to_message)

        # Node 2: Retrieve documents with vectorstore wrapper
        def document_retrieval_with_vectorstore(state: RoutingState) -> RoutingState:
            """Wrapper to inject vectorstore into document retrieval node."""
            # Ensure related_pages exists
            if "related_pages" not in state:
                state["related_pages"] = []

            result = document_retrieval_node(state, self.vectorstore)
            logger.debug(f"[ROUTING] Retrieved {len(result.get('related_pages', []))} documents")
            return result

        builder.add_node("document_retrieval", document_retrieval_with_vectorstore)

        # Add edges: START → normalize → retrieval → END
        builder.add_edge(START, "normalize_messages")
        builder.add_edge("normalize_messages", "document_retrieval")
        builder.add_edge("document_retrieval", END)

        # Compile
        compiled = builder.compile(
            name="routing_graph",
            checkpointer=self.get_memory(),
        )

        logger.info("[ROUTING] Graph built successfully")
        return compiled
