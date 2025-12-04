"""
Forza Navigation Graph Implementation.

Complete page routing and parameter extraction agent with alternative fallback logic.
"""

import logging
from pathlib import Path
from typing import Optional
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

from .states import NavigationState
from .nodes import (
    extract_user_input_node,
    find_documents_node,
    select_most_relevant_document,
    detect_page_parameters_node,
    extract_page_parameters_node,
    update_url_with_parameters_node,
    format_navigation_output_node,
    validate_tool_results_node,
    find_alternative_pages_node,
)

logger = logging.getLogger(__name__)
config = ConfigLoader.load_config("config/config.yaml")


@register_graph("routing")
class RoutingGraph(BaseGraph):
    """
    Complete Forza navigation graph with parameter extraction and fallback logic.

    Multi-stage architecture:
    1. Document Retrieval: Finds similar pages using embeddings
    2. Selection: Picks the most relevant page
    3. Parameter Detection: Checks if page has URL parameters
    4. Parameter Extraction: Uses tools to fill parameters
    5. Validation: Validates tool results
    6. Alternative Fallback: Finds alternatives if extraction fails
    7. URL Update: Fills parameters in URL
    8. Output Formatting: Generates final output with tool message

    Features:
    - Comprehensive parameter extraction with LLM-guided tool usage
    - Automatic fallback to alternative pages
    - Tool result validation
    - Clean output formatting for frontend
    - Proper integration with supervisor via tool messages
    """

    def __init__(self, llm: LLM, config: Optional[GraphConfig] = None):
        """
        Initialize ForzaRoutingGraph.

        Args:
            llm: Language model instance
            config: Optional GraphConfig instance
        """
        if config is None:
            try:
                config = GraphConfig.from_yaml("src/graphs/forza_routing/config.yaml")
                logger.info("[FORZA] Loaded config from YAML")
            except FileNotFoundError:
                logger.warning("[FORZA] Config file not found, using defaults")
                config = GraphConfig(name="forza_routing")

        super().__init__(
            llm=llm,
            state_class=NavigationState,
            config=config,
            metadata=self._get_default_metadata()
        )

        self.vectorstore = self._setup_vectorstore()
        if self.vectorstore:
            logger.info("[FORZA] ForzaRoutingGraph initialized successfully")
        else:
            logger.warning("[FORZA] Vectorstore initialization failed")

    def _get_default_metadata(self) -> GraphMetadata:
        """
        Get default metadata for Forza routing graph.

        Returns:
            GraphMetadata describing the graph capabilities and interface
        """
        return GraphMetadata(
            name="forza_routing",
            category="navigation",
            capabilities=[
                GraphCapability.TEXT_UNDERSTANDING,
            ],
            input_spec=InputSpec(
                name="messages",
                type="list[AnyMessage]",
                description="User messages for page routing and parameter extraction",
            ),
            output_spec=OutputSpec(
                name="navigation_output",
                type="NavigationOutput",
                description="Complete navigation output with URL and parameters",
            ),
            version="2.0.0",
            tags=[
                "routing",
                "navigation",
                "forza",
                "document-retrieval",
                "web-page-navigation",
                "parameter-extraction",
                "tool-execution",
                "fallback-mechanism",
                "langgraph-compatible",
                "high-performance",
            ],
        )

    def _setup_vectorstore(self) -> Optional[Chroma]:
        """
        Initialize Chroma vectorstore for document retrieval.

        Handles both dev and production (frozen exe) environments.

        Returns:
            Initialized Chroma vectorstore or None if setup fails
        """
        try:
            logger.info("[FORZA] Initializing vectorstore...")

            # Get base path
            base_path = self._get_base_path()
            vectorstore_path = base_path / "data" / "vector_index" / "vegaforza_chroma_db"

            logger.debug(f"[FORZA] Base path: {base_path}")
            logger.debug(f"[FORZA] Vectorstore path: {vectorstore_path}")

            # Validate path
            if not vectorstore_path.exists():
                logger.error(f"[FORZA] Vectorstore path not found: {vectorstore_path}")
                return None

            # Setup embeddings
            embeddings = OpenAIEmbeddings(
                model="text-embedding-3-small",
                openai_api_key=config.llm.api_key,
                base_url=config.llm.base_url,
            )

            # Initialize Chroma
            chroma_settings = Settings(
                anonymized_telemetry=False,
                allow_reset=True,
                chroma_api_impl="chromadb.api.segment.SegmentAPI"
            )

            chroma_client = chromadb.PersistentClient(
                path=str(vectorstore_path),
                settings=chroma_settings
            )

            # Validate collection
            try:
                collection = chroma_client.get_collection("vegaforza_web_pages")
                doc_count = collection.count()

                if doc_count == 0:
                    logger.warning("[FORZA] Collection is empty")
                    return None

                logger.info(f"[FORZA] Collection ready - {doc_count} pages")

            except Exception as e:
                logger.error(f"[FORZA] Collection validation failed: {e}")
                return None

            # Create vectorstore
            vectorstore = Chroma(
                client=chroma_client,
                collection_name="vegaforza_web_pages",
                embedding_function=embeddings,
            )

            logger.info("[FORZA] Vectorstore initialized successfully")
            return vectorstore

        except Exception as e:
            logger.error(f"[FORZA] Vectorstore initialization failed: {e}", exc_info=True)
            return None

    def _get_base_path(self) -> Path:
        """Get project base path (works in both dev and exe environments)."""
        is_frozen = getattr(sys, "frozen", False)
        if is_frozen:
            base_path = Path(sys.executable).parent
            logger.debug("[FORZA] Running as frozen executable")
        else:
            # graph.py: forza-chatbot/src/graphs/forza_routing/graph.py
            # Go up 4 levels to reach project root
            base_path = Path(__file__).resolve().parent.parent.parent.parent
            logger.debug("[FORZA] Running as script")
        return base_path

    def build_graph(self) -> StateGraph:
        """
        Build the Forza routing graph with all nodes and edges.

        Graph Flow:
            1. extract_user_input: Extract query from messages
            2. find_documents: Search vectorstore
            3. select_most_relevant_document: Pick best match
            4. detect_page_parameters: Check for URL parameters
            5. [Conditional] extract_page_parameters or skip
            6. validate_tool_results: Check if tools succeeded
            7. [Conditional] find_alternative_pages or continue
            8. update_url_with_parameters: Fill URL placeholders
            9. format_navigation_output: Format final output
            10. END

        Returns:
            Compiled StateGraph ready for execution
        """
        builder = self.get_graph_builder()

        # =====================
        # Node Registration
        # =====================

        # Create wrappers for nodes that need extra parameters
        def wrapped_find_docs(state: NavigationState) -> NavigationState:
            return find_documents_node(state, vectorstore=self.vectorstore)

        def wrapped_extract_params(state: NavigationState) -> NavigationState:
            return extract_page_parameters_node(state, self.llm, config)

        builder.add_node("extract_user_input", extract_user_input_node)
        builder.add_node("find_documents", wrapped_find_docs)
        builder.add_node("select_most_relevant_document", select_most_relevant_document)
        builder.add_node("detect_page_parameters", detect_page_parameters_node)
        builder.add_node("extract_page_parameters", wrapped_extract_params)
        builder.add_node("validate_tool_results", validate_tool_results_node)
        builder.add_node("find_alternative_pages", find_alternative_pages_node)
        builder.add_node("update_url_with_parameters", update_url_with_parameters_node)
        builder.add_node("format_navigation_output", format_navigation_output_node)

        # =====================
        # Edge Configuration
        # =====================

        # Linear pipeline
        builder.add_edge(START, "extract_user_input")
        builder.add_edge("extract_user_input", "find_documents")
        builder.add_edge("find_documents", "select_most_relevant_document")
        builder.add_edge("select_most_relevant_document", "detect_page_parameters")

        # Branch 1: Has parameters -> Extract | No parameters -> Validate
        builder.add_conditional_edges(
            "detect_page_parameters",
            lambda state: "has_parameters" if state.get("has_parameters") else "no_parameters",
            {
                "has_parameters": "extract_page_parameters",
                "no_parameters": "validate_tool_results"
            }
        )

        # Parameter extraction always goes to validation
        builder.add_edge("extract_page_parameters", "validate_tool_results")

        # Branch 2: Valid results -> Update URL | Invalid -> Find alternatives
        builder.add_conditional_edges(
            "validate_tool_results",
            self._should_find_alternatives,
            {
                "continue": "update_url_with_parameters",
                "find_alternatives": "find_alternative_pages"
            }
        )

        # If no more alternatives, go to URL update anyway
        builder.add_edge("find_alternative_pages", "validate_tool_results")

        # Final pipeline
        builder.add_edge("update_url_with_parameters", "format_navigation_output")
        builder.add_edge("format_navigation_output", END)

        logger.info("[FORZA] Graph built successfully")
        return builder.compile()

    def _should_find_alternatives(self, state: NavigationState) -> str:
        """
        Determine if we should find alternative pages.

        Returns:
            "continue" to proceed with URL update
            "find_alternatives" to search for alternatives
        """
        tool_results_valid = state.get("tool_results_valid", False)
        no_more_alternatives = state.get("no_more_alternatives", False)

        if no_more_alternatives or tool_results_valid:
            logger.debug("[FORZA] Continuing to URL update")
            return "continue"
        else:
            logger.debug("[FORZA] Searching for alternative pages")
            return "find_alternatives"
