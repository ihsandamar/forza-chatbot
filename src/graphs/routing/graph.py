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

from src.graphs.routing.assistant_configuration import RoutingAssistantConfiguration
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
    extract_category_from_query,
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
class RoutingGraph(BaseGraph[RoutingAssistantConfiguration]):
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

    def __init__(self, llm: LLM, config: Optional[RoutingAssistantConfiguration] = None):
        """
        Initialize RoutingGraph.

        Args:
            llm: Language model instance
            config: Optional RoutingAssistantConfiguration instance
        """
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

        # Create node kit with config (will hold all node logic)
        # Import here to avoid circular imports
        from src.graphs.routing.nodes import RoutingNodeKit
        from src.services.config_loader import ConfigLoader

        global_config = ConfigLoader.load_config("config/config.yaml")
        self.node_kit = RoutingNodeKit(
            llm=self.llm,
            config=self.config,
            vectorstore=self.vectorstore,
            global_config=global_config
        )
        logger.debug("[FORZA] RoutingNodeKit initialized")

    def _get_default_config(self) -> RoutingAssistantConfiguration:
        """
        Get default configuration for routing graph.

        Returns:
            RoutingAssistantConfiguration with default values

        Note:
            Token is intentionally empty and will be injected at runtime.
            Runtime token is injected into state by supervisor's prepare_routing_config node.
        """
        logger.debug("[FORZA] Using empty token, will be injected at runtime via state")

        return RoutingAssistantConfiguration(
            system_prompt="Sen Forza navigasyon asistanısın. Kullanıcıları doğru sayfalara yönlendirirsin.",
            assistant_name="RoutingAssistant",
            token=""  # Empty by design - injected at runtime
        )

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

    def _create_documents_from_catalog(self, catalog: dict) -> list:
        """Create LangChain Documents from forza.json catalog.

        Produces documents with all metadata fields routing nodes expect:
        title, url, url_route, category, page_id, document_type,
        sub_page_type, parent_page_id, has_parameters, parameter_count,
        url_parameters, keywords.
        """
        import json as _json
        from langchain_core.documents import Document

        documents = []
        for page in catalog.get("web_pages_catalog", []):
            metadata = page.get("metadata", {})
            structured_data = page.get("structured_data", {})

            # Build content for embedding
            content_parts = [page.get("embedding_content", "")]

            functions = structured_data.get("functions", [])
            if functions:
                content_parts.append("\n\nÖzellikler ve İşlevler:")
                content_parts.append("\n".join(f"- {func}" for func in functions))

            keywords = structured_data.get("keywords", [])
            if keywords:
                content_parts.append("\n\nAnahtar Kelimeler:")
                content_parts.append(", ".join(keywords))

            user_expressions = page.get("user_expressions", [])
            if user_expressions:
                content_parts.append("\n\nKullanıcı İfadeleri:")
                content_parts.append("\n".join(f"- {expr}" for expr in user_expressions))

            # URL parameters
            url_params = metadata.get("url_parameters", {}) or {}
            url_params_json = _json.dumps(url_params, ensure_ascii=False) if url_params else ""
            url_route = metadata.get("url_route", "")

            doc = Document(
                page_content="\n".join(content_parts),
                metadata={
                    "page_id": metadata.get("page_id", ""),
                    "title": metadata.get("title", ""),
                    "url": url_route,
                    "url_route": url_route,
                    "category": metadata.get("category", ""),
                    "document_type": metadata.get("page_type", "main_page"),
                    "sub_page_type": metadata.get("sub_page_type", ""),
                    "parent_page_id": metadata.get("parent_page_id", ""),
                    "keywords": ", ".join(keywords),
                    "has_parameters": len(url_params) > 0,
                    "parameter_count": len(url_params),
                    "url_parameters": url_params_json,
                    "source": "forza_web_catalog",
                    "catalog_version": catalog.get("version", "unknown"),
                },
            )
            documents.append(doc)

        return documents

    def _setup_vectorstore(self) -> Optional[Chroma]:
        """
        Initialize Chroma vectorstore for document retrieval.

        If the collection doesn't exist, auto-creates it from data/forza.json.
        Handles both dev and production (frozen exe) environments.

        Returns:
            Initialized Chroma vectorstore or None if setup fails
        """
        try:
            logger.info("[FORZA] Initializing vectorstore...")

            # Get persist directory from config, resolved relative to project root
            base_path = self._get_base_path()
            vectorstore_path = (base_path / config.vector_store.persist_directory).resolve()

            logger.debug(f"[FORZA] Vectorstore path: {vectorstore_path}")

            # Create directory if it doesn't exist
            vectorstore_path.mkdir(parents=True, exist_ok=True)

            # Setup embeddings from config
            embeddings = OpenAIEmbeddings(
                model=config.embedding.model,
                openai_api_key=config.embedding.api_key,
                base_url=config.embedding.base_url,
            )

            # Initialize Chroma client (single instance, reused for both load and create)
            chroma_settings = Settings(
                anonymized_telemetry=False,
                allow_reset=True,
                chroma_api_impl="chromadb.api.segment.SegmentAPI"
            )

            try:
                chroma_client = chromadb.PersistentClient(
                    path=str(vectorstore_path),
                    settings=chroma_settings
                )
            except Exception as e:
                # Corrupt/incompatible sqlite3 from old ChromaDB version — reset and retry
                logger.warning(f"[FORZA] Corrupt vectorstore DB, resetting: {e}")
                db_file = vectorstore_path / "chroma.sqlite3"
                if db_file.exists():
                    db_file.unlink()
                chroma_client = chromadb.PersistentClient(
                    path=str(vectorstore_path),
                    settings=chroma_settings
                )

            # Try to load existing collection
            try:
                collection = chroma_client.get_collection("forza_web_pages")
                doc_count = collection.count()

                if doc_count == 0:
                    logger.warning("[FORZA] Collection is empty, re-creating...")
                    chroma_client.delete_collection("forza_web_pages")
                    return self._auto_create_collection(base_path, chroma_client, embeddings)

                logger.info(f"[FORZA] Collection ready - {doc_count} pages")

                vectorstore = Chroma(
                    client=chroma_client,
                    collection_name="forza_web_pages",
                    embedding_function=embeddings,
                )

                logger.info("[FORZA] Vectorstore initialized successfully")
                return vectorstore

            except Exception as e:
                logger.warning(f"[FORZA] Collection not available: {e}")
                logger.info("[FORZA] Attempting auto-creation from forza.json...")
                return self._auto_create_collection(base_path, chroma_client, embeddings)

        except Exception as e:
            logger.error(f"[FORZA] Vectorstore initialization failed: {e}", exc_info=True)
            return None

    def _auto_create_collection(self, base_path: Path, chroma_client, embeddings) -> Optional[Chroma]:
        """Auto-create forza_web_pages collection from data/forza.json.

        Uses the already-created chroma_client to avoid dual PersistentClient
        locking conflicts on the same directory.
        """
        import json as _json

        catalog_path = base_path / "data" / "forza.json"
        if not catalog_path.exists():
            logger.error(f"[FORZA] Catalog not found: {catalog_path} — cannot auto-create")
            return None

        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                catalog = _json.load(f)

            documents = self._create_documents_from_catalog(catalog)
            if not documents:
                logger.error("[FORZA] No documents created from catalog")
                return None

            logger.info(f"[FORZA] Creating collection from {len(documents)} pages...")

            vectorstore = Chroma.from_documents(
                documents=documents,
                embedding=embeddings,
                collection_name="forza_web_pages",
                client=chroma_client,
            )

            logger.info(f"[FORZA] Auto-created forza_web_pages with {len(documents)} documents")
            return vectorstore

        except Exception as e:
            logger.error(f"[FORZA] Auto-creation failed: {e}", exc_info=True)
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

        Uses RoutingNodeKit pattern for cleaner configuration management.
        Token is now accessed from config, not state.

        Graph Flow:
            1. extract_user_input: Extract query from messages
            2. extract_category: Extract category from query using LLM
            3. find_documents: Search vectorstore (with category filter)
            4. select_most_relevant_document: Pick best match
            5. detect_page_parameters: Check for URL parameters
            6. [Conditional] extract_page_parameters or skip
            7. validate_tool_results: Check if tools succeeded
            8. [Conditional] find_alternative_pages or continue
            9. update_url_with_parameters: Fill URL placeholders
            10. format_navigation_output: Format final output
            11. END

        Returns:
            Compiled StateGraph ready for execution
        """
        builder = self.get_graph_builder()

        # =====================
        # Node Registration - Using RoutingNodeKit Pattern
        # =====================
        # All nodes are now methods of node_kit, which holds config and dependencies

        logger.info("[FORZA] Registering nodes using RoutingNodeKit pattern...")

        builder.add_node("extract_user_input", self.node_kit.extract_user_input_node)
        builder.add_node("extract_category", self.node_kit.extract_category_from_query)
        builder.add_node("find_documents", self.node_kit.find_documents_node)
        builder.add_node("select_most_relevant_document", self.node_kit.select_most_relevant_document_node)
        builder.add_node("detect_page_parameters", self.node_kit.detect_page_parameters_node)
        builder.add_node("extract_page_parameters", self.node_kit.extract_page_parameters_node)
        builder.add_node("validate_tool_results", self.node_kit.validate_tool_results_node)
        builder.add_node("find_alternative_pages", self.node_kit.find_alternative_pages_node)
        builder.add_node("update_url_with_parameters", self.node_kit.update_url_with_parameters_node)
        builder.add_node("format_navigation_output", self.node_kit.format_navigation_output_node)

        # =====================
        # Edge Configuration
        # =====================

        # Linear pipeline
        builder.add_edge(START, "extract_user_input")
        builder.add_edge("extract_user_input", "extract_category")
        builder.add_edge("extract_category", "find_documents")
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
