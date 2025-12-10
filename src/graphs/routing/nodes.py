"""
Forza Navigation Graph Node Implementations.

Function-based nodes for document retrieval, parameter extraction, and URL building.
"""

import json
import logging
import re
import traceback
from typing import Any, Dict, Optional

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.models.llm import LLM
from src.tools.forza_routing_toolkit import ForzaRoutingToolkit

from .states import NavigationState, NavigationOutput
from .exceptions import (
    ForzaRoutingBaseException,
    VectorStoreNotFoundError,
    UserInputExtractionError,
    DocumentRetrievalError,
    DocumentSelectionError,
    ParameterDetectionError,
    ParameterExtractionError,
    ToolExecutionError,
    URLUpdateError,
    OutputFormattingError,
    AlternativePageSearchError,
    InvalidStateError,
)

logger = logging.getLogger(__name__)

# Constants
SIMILARITY_SEARCH_K = 5
MAX_RETRIES = 3
SIMILARITY_SCORE_THRESHOLD = 0.3  # Minimum similarity score to consider


def extract_user_input_node(state: NavigationState) -> NavigationState:
    """Extract user input from last HumanMessage in messages and load token from config."""
    try:
        messages = state.get("messages", [])
        if not messages:
            logger.error("[FORZA] No messages found in state")
            raise UserInputExtractionError("No messages found in state")

        # Find the last HumanMessage (user input)
        # Iterate in reverse to find the most recent user message
        user_message = None
        for msg in reversed(messages):
            # Check if message is a HumanMessage
            if isinstance(msg, HumanMessage):
                user_message = msg
                break
            # Fallback: check by class name for compatibility
            elif hasattr(msg, '__class__') and msg.__class__.__name__ == 'HumanMessage':
                user_message = msg
                break

        if not user_message:
            logger.error("[FORZA] No HumanMessage found in messages")
            raise UserInputExtractionError("No HumanMessage found in messages")

        user_input = (
            user_message.content
            if isinstance(user_message.content, str)
            else str(user_message.content)
        ).strip()

        if not user_input:
            logger.error("[FORZA] Extracted user input is empty")
            raise UserInputExtractionError("User input is empty after extraction")

        state["user_input"] = user_input
        logger.debug(f"[FORZA] Extracted user input: {user_input[:100]}...")

        # Load token from config
        from src.services.config_loader import ConfigLoader
        config = ConfigLoader.load_config("config/config.yaml")
        token = config.forza.token

        if not token:
            logger.error("[FORZA] Token not found in config")
            raise UserInputExtractionError("Token not found in config.forza.token")

        state["token"] = token
        logger.debug("[FORZA] Token loaded from config successfully")

        return state

    except UserInputExtractionError:
        raise
    except Exception as e:
        logger.error(f"[FORZA] Unexpected error extracting user input: {e}", exc_info=True)
        raise UserInputExtractionError(f"Failed to extract user input: {str(e)}") from e


def extract_category_from_query(state: NavigationState, llm: LLM) -> NavigationState:
    """Extract category from user query using llm invoke."""
    try:
        user_input = state.get("user_input", "")

        # Get categories directly from JSON
        import json
        try:
            with open("data/forza.json", "r", encoding="utf-8") as f:
                catalog_data = json.load(f)

            # Extract unique categories from web_pages_catalog
            categories = set()
            for page_data in catalog_data.get("web_pages_catalog", []):
                metadata = page_data.get("metadata", {})
                category = metadata.get("category")
                if category:
                    categories.add(category)

            categories = list(categories)
            logger.debug(f"[FORZA] Found {len(categories)} categories: {categories}")

        except Exception as e:
            logger.warning(f"[FORZA] Could not load categories from catalog: {e}")
            categories = []

        if not categories:
            logger.warning("[FORZA] No categories found, skipping category extraction")
            state["extracted_category"] = None
            return state

        matched_category = None

        # llm invoke to find category
        prompt = f"""Kullanıcı isteği: "{user_input}"
Aşağıdaki kategorilerden hangisi bu isteğe en uygun olanıdır? Eğer hiçbiri uygun değilse "None" olarak cevapla.
Kategoriler: {', '.join(categories)}
Cevap sadece kategori adı veya "None" olmalıdır."""
        response = llm.get_chat().invoke([HumanMessage(content=prompt)])

        response_text = response.content.strip()
        if response_text in categories:
            matched_category = response_text
        elif response_text.lower() == "none":
            matched_category = None
        else:
            logger.warning(f"[FORZA] LLM returned unknown category: {response_text}")
            matched_category = None

        state["extracted_category"] = matched_category
        logger.info(f"[FORZA] Extracted category: {matched_category}")

        return state

    except Exception as e:
        logger.error(f"[FORZA] Unexpected error extracting category: {e}", exc_info=True)
        raise ForzaRoutingBaseException(f"Category extraction failed: {str(e)}") from e
    





def find_documents_node(
    state: NavigationState, vectorstore: Optional[Chroma] = None
) -> NavigationState:
    """
    Retrieve similar documents using vectorstore with optional metadata filtering.

    Uses similarity_search_with_score for better relevance scoring and supports
    filtering by category, parameters, and other metadata fields.
    """
    try:
        if not vectorstore:
            logger.error("[FORZA] Vectorstore not available")
            raise VectorStoreNotFoundError("Vectorstore is not initialized")

        user_input = state.get("user_input", "")
        if not user_input:
            logger.error("[FORZA] Empty user input for document retrieval")
            raise DocumentRetrievalError("User input is empty or missing")

        # Build metadata filter if needed
        metadata_filter = _build_metadata_filter(state)

        # Use similarity_search_with_score for better scoring
        try:
            if metadata_filter:
                logger.debug(f"[FORZA] Applying metadata filter: {metadata_filter}")
                retrieved_docs_with_scores = vectorstore.similarity_search_with_score(
                    user_input,
                    k=SIMILARITY_SEARCH_K,
                    filter=metadata_filter
                )
            else:
                retrieved_docs_with_scores = vectorstore.similarity_search_with_score(
                    user_input,
                    k=SIMILARITY_SEARCH_K
                )
        except Exception as e:
            # Fallback to basic search if filtering fails
            logger.warning(f"[FORZA] Metadata filtering failed, using basic search: {e}")
            retrieved_docs = vectorstore.similarity_search(user_input, k=SIMILARITY_SEARCH_K)
            retrieved_docs_with_scores = [(doc, 1.0 - (i * 0.1)) for i, doc in enumerate(retrieved_docs)]

        if not retrieved_docs_with_scores:
            logger.error("[FORZA] No documents found for user input")
            raise DocumentRetrievalError(f"No similar documents found for query: {user_input[:100]}")

        # Filter by score threshold and convert scores (lower distance = higher similarity)
        # ChromaDB returns L2 distance, convert to similarity score
        docs_with_scores = []
        for doc, distance in retrieved_docs_with_scores:
            # Convert distance to similarity (0-1 range, higher is better)
            similarity_score = 1.0 / (1.0 + distance)

            if similarity_score >= SIMILARITY_SCORE_THRESHOLD:
                docs_with_scores.append((doc, similarity_score))
                logger.debug(
                    f"[FORZA] Retrieved: {doc.metadata.get('title', 'Unknown')} "
                    f"(score: {similarity_score:.3f}, distance: {distance:.3f})"
                )

        if not docs_with_scores:
            logger.warning(f"[FORZA] No documents above threshold {SIMILARITY_SCORE_THRESHOLD}")
            raise DocumentRetrievalError(
                f"No sufficiently similar documents found (threshold: {SIMILARITY_SCORE_THRESHOLD})"
            )

        # Sort by score (descending)
        docs_with_scores.sort(key=lambda x: x[1], reverse=True)

        state["related_pages"] = docs_with_scores
        logger.info(
            f"[FORZA] Retrieved {len(docs_with_scores)} documents "
            f"(best score: {docs_with_scores[0][1]:.3f})"
        )
        return state

    except (VectorStoreNotFoundError, DocumentRetrievalError):
        raise
    except Exception as e:
        logger.error(f"[FORZA] Unexpected error during document retrieval: {e}", exc_info=True)
        raise DocumentRetrievalError(f"Document retrieval failed: {str(e)}") from e


def select_most_relevant_document(state: NavigationState) -> NavigationState:
    """Select the highest-scoring document."""
    try:
        related_pages = state.get("related_pages", [])
        if not related_pages:
            logger.error("[FORZA] No related pages available for selection")
            raise DocumentSelectionError("No documents available in related_pages")

        # First document has highest score
        most_related_doc, score = related_pages[0]
        state["most_related_document"] = most_related_doc

        title = most_related_doc.metadata.get("title", "Unknown")
        logger.info(f"[FORZA] Selected page: {title} (score: {score:.3f})")

        return state

    except DocumentSelectionError:
        raise
    except Exception as e:
        logger.error(f"[FORZA] Unexpected error selecting document: {e}", exc_info=True)
        raise DocumentSelectionError(f"Document selection failed: {str(e)}") from e


def detect_page_parameters_node(state: NavigationState) -> NavigationState:
    """
    Check if page has URL parameters.

    Uses the new metadata structure:
    - has_parameters: boolean indicating if page has parameters
    - parameter_count: number of parameters (optional)
    - URL contains {parameter} placeholders
    """
    try:
        doc = state.get("most_related_document")
        if not doc:
            logger.error("[FORZA] No most_related_document found in state")
            raise ParameterDetectionError("most_related_document is missing from state")

        metadata = doc.metadata or {}

        # Check using new metadata structure first
        has_params = metadata.get("has_parameters", False)

        # Fallback: Check URL for parameter placeholders (excluding base_url)
        if not has_params:
            url = metadata.get("url", "")
            if url and "{" in url and "}" in url:
                import re
                param_names = re.findall(r'\{(\w+)\}', url)
                # Filter out base_url placeholders - they are not real parameters
                param_names = [p for p in param_names if not _is_base_url_parameter(p)]
                has_params = bool(param_names)

        # Fallback: Check old metadata structure (also filter base_url)
        if not has_params:
            url_params = _parse_url_parameters(metadata.get("url_parameters", {}))
            # Filter out base_url parameters
            url_params = {k: v for k, v in (url_params or {}).items() if not _is_base_url_parameter(k)}
            has_params = bool(url_params and len(url_params) > 0)

        state["has_parameters"] = has_params

        param_count = metadata.get("parameter_count", 0)
        logger.debug(
            f"[FORZA] Page '{metadata.get('title', 'Unknown')}' has parameters: {has_params} "
            f"(count: {param_count})"
        )

        return state

    except ParameterDetectionError:
        raise
    except Exception as e:
        logger.error(f"[FORZA] Unexpected error detecting parameters: {e}", exc_info=True)
        raise ParameterDetectionError(f"Parameter detection failed: {str(e)}") from e


def extract_page_parameters_node(
    state: NavigationState, llm: LLM, config: Any
) -> NavigationState:
    """
    Extract URL parameters using tools.

    Supports multiple parameter sources:
    1. url_parameters metadata (dict or JSON string)
    2. URL placeholder extraction (fallback)
    """
    try:
        if not state.get("has_parameters"):
            logger.debug("[FORZA] Page has no parameters, skipping extraction")
            return state

        doc = state.get("most_related_document")
        if not doc:
            logger.error("[FORZA] No most_related_document found in state")
            raise ParameterExtractionError("most_related_document is missing from state")

        token = state.get("token")
        if not token:
            logger.error("[FORZA] No authentication token available")
            raise ParameterExtractionError("Authentication token is missing from state")

        metadata = doc.metadata or {}
        page_title = metadata.get("title", "")

        # Try to get url_parameters from metadata
        url_params = _parse_url_parameters(metadata.get("url_parameters"))

        # Fallback: Extract from URL placeholders if url_parameters not found
        if not url_params:
            logger.warning("[FORZA] No url_parameters in metadata, extracting from URL...")
            url = metadata.get("url") or metadata.get("url_route", "")

            if url and "{" in url and "}" in url:
                # Extract parameter names from URL
                import re
                param_names = re.findall(r'\{(\w+)\}', url)

                if param_names:
                    # Create basic url_parameters structure
                    url_params = {}
                    for param_name in param_names:
                        # Skip base_url placeholders
                        if _is_base_url_parameter(param_name):
                            logger.debug(f"[FORZA] Skipping base_url placeholder: {param_name}")
                            continue

                        url_params[param_name] = {
                            "type": "guid",  # Default type
                            "description": f"Parameter: {param_name}",
                            "required": True,
                            "endpoint": _guess_endpoint_from_param_name(param_name)
                        }
                    logger.info(f"[FORZA] Extracted {len(url_params)} real parameters from URL")
                else:
                    logger.warning("[FORZA] Could not extract parameters from URL")
            else:
                logger.warning("[FORZA] URL has no parameter placeholders")

        # Filter out base_url parameters (in case they were in metadata)
        if url_params:
            url_params = {k: v for k, v in url_params.items() if not _is_base_url_parameter(k)}

        if not url_params:
            logger.debug("[FORZA] No real parameters to fill (only base_url placeholders)")
            # Don't run tools if only base_url needs to be filled
            return state

        # Create toolkit and execute tools
        toolkit = ForzaRoutingToolkit(
            base_url=config.forza.base_url,
            token=token
        )

        filled_params = _execute_tools_for_parameters(
            state, llm, page_title, url_params, toolkit
        )

        if filled_params:
            state["filled_parameters"] = filled_params
            logger.info(f"[FORZA] Successfully filled {len(filled_params)} parameters")
        else:
            logger.warning("[FORZA] Tool execution did not fill any parameters")

        return state

    except ParameterExtractionError:
        raise
    except Exception as e:
        logger.error(f"[FORZA] Unexpected error during parameter extraction: {e}", exc_info=True)
        raise ParameterExtractionError(f"Parameter extraction failed: {str(e)}") from e


def update_url_with_parameters_node(state: NavigationState) -> NavigationState:
    """
    Update URL with filled parameters.

    Works with both old (url_route) and new (url) metadata structures.
    """
    try:
        doc = state.get("most_related_document")
        if not doc:
            logger.error("[FORZA] No most_related_document found for URL update")
            raise URLUpdateError("most_related_document is missing from state")

        metadata = doc.metadata
        if not metadata:
            logger.error("[FORZA] Document metadata is missing")
            raise URLUpdateError("Document metadata is missing")

        # Try new structure first, fallback to old
        original_url = metadata.get("url") or metadata.get("url_route", "")
        if not original_url:
            logger.error("[FORZA] URL not found in document metadata")
            raise URLUpdateError("URL not found in document metadata")

        updated_url = original_url

        # Fill parameters if available
        filled_params = state.get("filled_parameters", {})
        if filled_params and state.get("has_parameters"):
            for param_name, param_data in filled_params.items():
                if isinstance(param_data, dict) and "value" in param_data:
                    placeholder = f"{{{param_name}}}"
                    value = param_data["value"]

                    if placeholder in updated_url and value:
                        updated_url = updated_url.replace(placeholder, str(value))
                        logger.debug(f"[FORZA] Updated {param_name}: {value}")

        # Apply baseUrl replacement (support multiple formats)
        from src.services.config_loader import ConfigLoader
        config = ConfigLoader.load_config("config/config.yaml")
        web_site_url = config.forza.web_site_url

        # Support multiple baseUrl formats: {baseUrl}, {base_url}, {BASE_URL}
        base_url_variants = [
            "{baseUrl}",
            "{base_url}",
            "{BASE_URL}",
            "{BaseUrl}",
            "{BASEURL}"
        ]

        for variant in base_url_variants:
            if variant in updated_url:
                updated_url = updated_url.replace(variant, web_site_url)
                logger.debug(f"[FORZA] Replaced {variant} with {web_site_url}")

        # Check for remaining placeholders (indicates parameter filling failed)
        import re
        remaining_placeholders = re.findall(r'\{(\w+)\}', updated_url)

        if remaining_placeholders:
            # Remove base_url placeholders (they're expected and will be filled)
            param_placeholders = [p for p in remaining_placeholders if not _is_base_url_parameter(p)]

            if param_placeholders:
                logger.warning(
                    f"[FORZA] URL still contains unfilled placeholders: {param_placeholders} "
                    f"- Parameter filling may have failed"
                )
                state["has_unfilled_parameters"] = True
                state["unfilled_parameters"] = param_placeholders

        # Update document if URL changed
        if updated_url != original_url:
            updated_metadata = metadata.copy()
            # Update both url and url_route for backwards compatibility
            updated_metadata["url"] = updated_url
            updated_metadata["url_route"] = updated_url
            updated_metadata["original_url"] = original_url

            state["most_related_document"] = Document(
                page_content=doc.page_content,
                metadata=updated_metadata
            )
            logger.debug(f"[FORZA] URL updated: {original_url} -> {updated_url}")
        else:
            logger.debug(f"[FORZA] URL unchanged: {original_url}")

        return state

    except URLUpdateError:
        raise
    except Exception as e:
        logger.error(f"[FORZA] Unexpected error during URL update: {e}", exc_info=True)
        raise URLUpdateError(f"URL update failed: {str(e)}") from e


def format_navigation_output_node(state: NavigationState) -> NavigationState:
    """Format final navigation output and add URL as tool message."""
    try:
        doc = state.get("most_related_document")

        if not doc:
            logger.warning("[FORZA] No document found, creating empty output")
            output = _create_empty_output()
        else:
            output = _document_to_navigation_output(doc)

        if not output:
            logger.error("[FORZA] Failed to create navigation output")
            raise OutputFormattingError("Navigation output formatting failed")

        state["navigation_output"] = output

        # Add URL as tool message pair
        if output.get("url"):
            url = output["url"]

            ai_message = AIMessage(
                content="",
                tool_calls=[{
                    "id": "routing_navigation_url",
                    "name": "navigation",
                    "args": {"url": url}
                }]
            )

            tool_message = ToolMessage(
                content=url,
                tool_call_id="routing_navigation_url"
            )

            messages = state.get("messages", [])
            if not isinstance(messages, list):
                messages = []

            state["messages"] = messages + [ai_message, tool_message]
            logger.debug(f"[FORZA] Navigation URL added: {url}")

        return state

    except OutputFormattingError:
        raise
    except Exception as e:
        logger.error(f"[FORZA] Unexpected error during output formatting: {e}", exc_info=True)
        raise OutputFormattingError(f"Output formatting failed: {str(e)}") from e


def validate_tool_results_node(state: NavigationState) -> NavigationState:
    """Check if parameters were successfully filled."""
    try:
        # If page doesn't require parameters, validation passes
        if not state.get("has_parameters"):
            logger.debug("[FORZA] Page has no parameters, validation passes")
            state["tool_results_valid"] = True
            return state

        filled_parameters = state.get("filled_parameters", {})

        if filled_parameters:
            state["tool_results_valid"] = True
            logger.debug(f"[FORZA] Tool results valid: {len(filled_parameters)} params")
        else:
            logger.warning("[FORZA] No filled parameters found, marking as invalid")
            state["tool_results_valid"] = False

        return state

    except Exception as e:
        logger.error(f"[FORZA] Unexpected error during tool validation: {e}", exc_info=True)
        # On error, assume validation failed
        state["tool_results_valid"] = False
        return state


def find_alternative_pages_node(state: NavigationState, vectorstore: Optional[Chroma] = None) -> NavigationState:
    """
    Find alternative pages when parameters cannot be filled.

    Strategy:
    1. Try other parametreli pages with same topic
    2. If all fail, try parametresiz pages as fallback
    3. If still no luck, mark as failed (don't return placeholder URLs)
    """
    try:
        retry_count = state.get("retry_count", 0)
        if retry_count >= MAX_RETRIES:
            logger.warning(f"[FORZA] Max retries ({MAX_RETRIES}) reached, trying parametresiz fallback")
            # Try to find a parametresiz alternative before giving up
            parametresiz_alternative = _find_parametresiz_alternative(state, vectorstore)
            if parametresiz_alternative:
                state["most_related_document"] = parametresiz_alternative
                state["has_parameters"] = False  # Mark as parametresiz
                state["no_more_alternatives"] = True
                state["tool_results_valid"] = True
                logger.info(f"[FORZA] Fallback to parametresiz page: {parametresiz_alternative.metadata.get('title')}")
                return state

            state["no_more_alternatives"] = True
            state["tool_results_valid"] = False  # ✓ Mark as failed, not valid!
            return state

        related_pages = state.get("related_pages", [])
        if not related_pages:
            logger.warning("[FORZA] No related pages available for alternatives")
            # Try parametresiz fallback
            parametresiz_alternative = _find_parametresiz_alternative(state, vectorstore)
            if parametresiz_alternative:
                state["most_related_document"] = parametresiz_alternative
                state["has_parameters"] = False
                state["no_more_alternatives"] = True
                state["tool_results_valid"] = True
                logger.info(f"[FORZA] Fallback to parametresiz page: {parametresiz_alternative.metadata.get('title')}")
                return state

            state["no_more_alternatives"] = True
            state["tool_results_valid"] = False  # ✓ Mark as failed!
            return state

        current_doc = state.get("most_related_document")
        current_page_id = current_doc.metadata.get("page_id") if current_doc else None

        tried_pages = state.get("tried_page_ids", set())
        if current_page_id:
            tried_pages.add(current_page_id)

        # Strategy 1: Try other parametreli alternatives
        found_alternative = False
        for doc, score in related_pages:
            page_id = doc.metadata.get("page_id")
            if page_id not in tried_pages:
                logger.info(
                    f"[FORZA] Found alternative: {doc.metadata.get('title')} "
                    f"(retry {retry_count + 1}/{MAX_RETRIES})"
                )
                state["most_related_document"] = doc
                state["tried_page_ids"] = tried_pages
                state["retry_count"] = retry_count + 1
                state["filled_parameters"] = {}
                state["tool_results_valid"] = None
                state["no_more_alternatives"] = False
                found_alternative = True
                return state

        # Strategy 2: No more parametreli alternatives, try parametresiz fallback
        if not found_alternative:
            logger.warning("[FORZA] No more parametreli alternatives, trying parametresiz fallback")
            parametresiz_alternative = _find_parametresiz_alternative(state, vectorstore)

            if parametresiz_alternative:
                state["most_related_document"] = parametresiz_alternative
                state["has_parameters"] = False
                state["tried_page_ids"] = tried_pages
                state["no_more_alternatives"] = True
                state["tool_results_valid"] = True
                logger.info(f"[FORZA] Fallback to parametresiz page: {parametresiz_alternative.metadata.get('title')}")
                return state

            # Strategy 3: Complete failure - no alternatives found
            logger.error("[FORZA] No alternatives found (parametreli or parametresiz)")
            state["tried_page_ids"] = tried_pages
            state["no_more_alternatives"] = True
            state["tool_results_valid"] = False  # ✓ Mark as failed!

        return state

    except Exception as e:
        logger.error(f"[FORZA] Unexpected error during alternative page search: {e}", exc_info=True)
        state["no_more_alternatives"] = True
        state["tool_results_valid"] = False  # ✓ Mark as failed!
        return state


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _is_base_url_parameter(param_name: str) -> bool:
    """
    Check if parameter name is a base_url placeholder.

    Base URL placeholders should not be treated as real parameters
    because they are automatically filled from config.forza.web_site_url.
    """
    base_url_names = ["baseUrl", "base_url", "BASE_URL", "BaseUrl", "BASEURL"]
    return param_name in base_url_names


def _find_parametresiz_alternative(state: NavigationState, vectorstore: Optional[Chroma] = None) -> Optional[Document]:
    """
    Find a parametresiz (no parameters) alternative page from related pages.
    If not found in related_pages, performs a new vector search for parametresiz pages.

    Args:
        state: Current navigation state
        vectorstore: Optional vectorstore for fallback search

    Returns:
        Document without parameters, or None if not found
    """
    related_pages = state.get("related_pages", [])
    if not related_pages:
        return None

    # Strategy 1: Look for parametresiz pages in related_pages
    for doc, score in related_pages:
        has_params = doc.metadata.get("has_parameters", False)

        # Check if parametresiz
        if not has_params:
            # Also check URL doesn't have real parameter placeholders (base_url is OK)
            url = doc.metadata.get("url") or doc.metadata.get("url_route", "")
            if url and url != "N/A":
                import re
                placeholders = re.findall(r'\{(\w+)\}', url)
                # Filter out base_url placeholders
                param_placeholders = [p for p in placeholders if not _is_base_url_parameter(p)]
                # If no real parameters, this is a valid parametresiz page
                if not param_placeholders:
                    logger.debug(f"[FORZA] Found parametresiz alternative in related_pages: {doc.metadata.get('title')}")
                    return doc

    # Strategy 2: If not found in related_pages, perform new vector search
    if vectorstore:
        logger.info("[FORZA] No parametresiz alternative in related_pages, performing new vector search...")
        user_input = state.get("user_input", "")

        try:
            # Search with metadata filter for parametresiz pages
            results = vectorstore.similarity_search_with_score(
                user_input,
                k=10,  # Search more to find parametresiz pages
                filter={"has_parameters": False}
            )

            # Find first valid parametresiz page
            for doc, distance in results:
                url = doc.metadata.get("url") or doc.metadata.get("url_route", "")
                if url and url != "N/A":
                    # Verify no real parameter placeholders (base_url is OK)
                    import re
                    placeholders = re.findall(r'\{(\w+)\}', url)
                    param_placeholders = [p for p in placeholders if not _is_base_url_parameter(p)]

                    if not param_placeholders:
                        logger.info(f"[FORZA] Found parametresiz alternative via new search: {doc.metadata.get('title')}")
                        return doc

        except Exception as e:
            logger.warning(f"[FORZA] Vector search for parametresiz fallback failed: {e}")

    # Not found anywhere
    logger.debug("[FORZA] No parametresiz alternative found")
    return None


def _build_metadata_filter(state: NavigationState) -> Optional[Dict[str, Any]]:
    """
    Build ChromaDB metadata filter from state.

    Supports filtering by:
    - category: Filter by page category (extracted from user query)
    - has_parameters: Filter by parameter presence
    - source: Filter by data source

    Returns:
        Metadata filter dict for ChromaDB, or None if no filtering needed
    """
    filters = {}

    # Priority 1: Use extracted category from LLM
    extracted_category = state.get("extracted_category")
    if extracted_category:
        filters["category"] = extracted_category
        logger.debug(f"[FORZA] Using extracted category filter: {extracted_category}")

    # Priority 2: Use explicit filter_category (manual override)
    elif "filter_category" in state and state["filter_category"]:
        filters["category"] = state["filter_category"]
        logger.debug(f"[FORZA] Using manual category filter: {state['filter_category']}")

    # Filter by parameter requirement
    if "filter_has_parameters" in state:
        filters["has_parameters"] = state["filter_has_parameters"]

    # Filter by source
    if "filter_source" in state and state["filter_source"]:
        filters["source"] = state["filter_source"]

    # Return None if no filters, otherwise return filter dict
    if not filters:
        return None

    logger.info(f"[FORZA] Built metadata filter: {filters}")
    return filters


def _parse_url_parameters(url_parameters: Any) -> Optional[Dict[str, Any]]:
    """Parse URL parameters from various formats."""
    if isinstance(url_parameters, str):
        try:
            return json.loads(url_parameters)
        except json.JSONDecodeError:
            logger.warning(f"[FORZA] Invalid JSON in url_parameters: {url_parameters}")
            return None
    return url_parameters or {}


def _guess_endpoint_from_param_name(param_name: str) -> str:
    """
    Guess API endpoint from parameter name.

    Common patterns:
    - cari_id -> api/Customers/getList
    - stok_id -> api/Items/getList
    - musteri_id -> api/Customers/getList
    """
    param_lower = param_name.lower()

    # Mapping of parameter names to endpoints
    endpoint_mapping = {
        "cari": "api/Customers/getList",
        "musteri": "api/Customers/getList",
        "customer": "api/Customers/getList",
        "stok": "api/Items/getList",
        "urun": "api/Items/getList",
        "item": "api/Items/getList",
        "siparis": "api/Orders/getList",
        "order": "api/Orders/getList",
        "fatura": "api/Invoices/getList",
        "invoice": "api/Invoices/getList",
    }

    # Check for matches
    for key, endpoint in endpoint_mapping.items():
        if key in param_lower:
            logger.debug(f"[FORZA] Guessed endpoint for '{param_name}': {endpoint}")
            return endpoint

    # Default fallback
    default_endpoint = "api/Customers/getList"
    logger.warning(
        f"[FORZA] Could not guess endpoint for '{param_name}', "
        f"using default: {default_endpoint}"
    )
    return default_endpoint


def _execute_tools_for_parameters(
    state: NavigationState,
    llm: LLM,
    page_title: str,
    url_parameters: Dict[str, Any],
    toolkit: ForzaRoutingToolkit
) -> Dict[str, Any]:
    """Execute tools to fill parameters."""
    try:
        tools = toolkit.get_tools()
        llm_with_tools = llm.get_chat().bind_tools(tools)

        # Build prompt for tool selection
        param_list = ", ".join(url_parameters.keys())
        prompt = f"""Kullanıcı isteği: "{state.get("user_input", "")}"
Hedef sayfa: "{page_title}"
Gerekli parametreler: {param_list}

Görev: Kullanıcı girdisinden ilgili bilgiyi çıkar ve uygun tool'ları çağır.

[CRITICAL] KRITIK TALİMAT:
Tool'a SADECE en genel/ana terimi TEK KELİME olarak gönder.

YASAKLAR:
- Marka isimleri kullanma
- Sıfatlar ekleme
- Birden fazla kelime kullanma
- Detay/açıklama ekleme

SADECE en genel terimi kullan."""

        logger.debug("[FORZA] Step 1: Sending prompt to LLM for tool selection...")
        messages = [HumanMessage(content=prompt)]
        response = llm_with_tools.invoke(messages)

        if not response.tool_calls:
            logger.warning("[FORZA] LLM did not make tool calls")
            return {}

        logger.debug(f"[FORZA] Step 2: Executing {len(response.tool_calls)} tool(s)...")
        messages.append(response)

        # Execute tools
        for tool_call in response.tool_calls:
            if isinstance(tool_call, dict):
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})
                tool_id = tool_call.get("id")
            else:
                tool_name = getattr(tool_call, "name", None)
                tool_args = getattr(tool_call, "args", {})
                tool_id = getattr(tool_call, "id", None)

            selected_tool = next((t for t in tools if t.name == tool_name), None)
            if not selected_tool:
                logger.warning(f"[FORZA] Tool '{tool_name}' not found")
                continue

            try:
                result = selected_tool.invoke(tool_args)
                logger.info(f"[FORZA] Tool '{tool_name}' executed successfully")
                logger.debug(f"[FORZA] Tool result: {json.dumps(result, ensure_ascii=False)[:200]}...")
                messages.append(
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=tool_id
                    )
                )
            except Exception as e:
                logger.error(f"[FORZA] Tool '{tool_name}' failed: {e}")
                messages.append(
                    ToolMessage(
                        content=json.dumps({"status": "error", "error": str(e)}),
                        tool_call_id=tool_id
                    )
                )

        # Check tool results validity
        logger.debug("[FORZA] Step 3: Checking tool results validity...")
        if not _check_tool_results_validity(messages):
            logger.warning("[FORZA] No valid tool results found")
            return {}

        # Ask LLM to format results
        logger.debug("[FORZA] Step 4: Asking LLM to format results...")
        final_prompt = f"""Kullanıcı isteği: "{state.get("user_input", "")}"

Tool'lardan aldığın sonuçlara göre parametreleri doldur.

Gerekli URL parametreleri: {json.dumps(url_parameters, ensure_ascii=False)}

GÖREV: Tool sonuçlarından KULLANICI İSTEĞİNE EN UYGUN kaydı bul ve parametreyi doldur.

ÇIKTI FORMATI (sadece JSON):
{{
  "parametre_ismi": {{
    "parameter_name": "parametre_ismi",
    "value": "id_değeri",
    "display_name": "görünen_isim"
  }}
}}

ÖRNEK:
Kullanıcı: "Ahmet Yılmaz"
Tool sonucu: [{{"id": "123-abc", "name": "Ahmet Yılmaz"}}, {{"id": "456-def", "name": "Mehmet Yılmaz"}}]
Parametre: cari_id

Çıktı:
{{
  "cari_id": {{
    "parameter_name": "cari_id",
    "value": "123-abc",
    "display_name": "Ahmet Yılmaz"
  }}
}}

KRİTİK KURALLAR:
1. Tool sonuçları BAŞARILI İSE → Kullanıcı isteğine EN UYGUN olanı seç
2. Tool sonuçları BOŞ veya HATALI İSE → Boş JSON döndür: {{}}
3. Kullanıcı isteğiyle EŞLEŞMİYORSA → Boş JSON döndür: {{}}
4. SADECE düz JSON döndür (açıklama yapma!)

Şimdi tool sonuçlarına bakarak parametreyi doldur (SADECE JSON):"""

        messages.append(HumanMessage(content=final_prompt))
        final_response = llm.get_chat().invoke(messages)

        # Parse JSON from response
        response_text = (
            final_response.content if hasattr(final_response, "content")
            else str(final_response)
        )

        # Log LLM response for debugging
        logger.info(f"[FORZA] LLM final response: {response_text[:300]}...")

        filled_parameters = None

        # Try markdown code block
        code_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
        if code_match:
            try:
                filled_parameters = json.loads(code_match.group(1))
                logger.debug("[FORZA] Extracted JSON from code block")
            except json.JSONDecodeError:
                pass

        # Try raw JSON
        if not filled_parameters:
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if json_match:
                try:
                    filled_parameters = json.loads(json_match.group())
                    logger.debug("[FORZA] Extracted raw JSON")
                except json.JSONDecodeError:
                    pass

        # Try entire response
        if not filled_parameters:
            try:
                filled_parameters = json.loads(response_text.strip())
                logger.debug("[FORZA] Entire response is JSON")
            except json.JSONDecodeError:
                pass

        if filled_parameters:
            logger.info(f"[FORZA] Successfully parsed parameters: {list(filled_parameters.keys())}")
            logger.debug(f"[FORZA] Filled parameters: {json.dumps(filled_parameters, ensure_ascii=False)}")
            return filled_parameters

        logger.error("[FORZA] Could not parse JSON from LLM response")
        logger.error(f"[FORZA] Raw LLM response: {response_text}")
        return {}

    except Exception as e:
        logger.error(f"[FORZA] LLM processing error: {e}")
        traceback.print_exc()
        return {}


def _check_tool_results_validity(messages: list) -> bool:
    """
    Check if any tool returned valid results.

    More flexible validity check - accepts multiple formats:
    - {"data": {"items": [...]}}
    - {"items": [...]}
    - {"success": true, "result": [...]}
    """
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue

        try:
            result = json.loads(msg.content)
            logger.debug(f"[FORZA] Checking tool result: {str(result)[:150]}...")

            # Skip error results
            if result.get("status") == "error":
                logger.debug("[FORZA] Tool result has error status, skipping")
                continue

            # Strategy 1: Check data field (old format)
            data = result.get("data", {})
            if data and isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, list) and len(value) > 0:
                        logger.info(f"[FORZA] Valid tool result found: {len(value)} {key} in data field")
                        return True

            # Strategy 2: Check root level lists (flexible format)
            for key, value in result.items():
                if key in ["data", "status", "error", "message"]:
                    continue  # Skip metadata fields

                if isinstance(value, list) and len(value) > 0:
                    logger.info(f"[FORZA] Valid tool result found: {len(value)} {key} at root level")
                    return True

                # Also check dict values that might contain lists
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        if isinstance(sub_value, list) and len(sub_value) > 0:
                            logger.info(f"[FORZA] Valid tool result found: {len(sub_value)} {key}.{sub_key}")
                            return True

        except (json.JSONDecodeError, AttributeError, KeyError) as e:
            logger.debug(f"[FORZA] Error parsing tool message: {e}")
            continue

    logger.warning("[FORZA] No valid tool results found in any message")
    return False


def _create_empty_output() -> NavigationOutput:
    """Create empty output when no document found."""
    return NavigationOutput(
        page_id="",
        page_title="Sayfa bulunamadı",
        url="",
        category="unknown",
        is_sub_page=False,
        sub_page_type=None,
        parent_page_id=None,
        parent_page_title=None,
        full_path=None,
        requires_parameters=False,
        parameters=None,
        confidence=0.0,
        reasoning="Uygun sayfa bulunamadı",
        suggestion_text="Arama kriterlerinizi değiştirip tekrar deneyiniz",
        cta_text="Tekrar Ara",
        alternative_suggestions=None
    )


def _document_to_navigation_output(document: Document) -> NavigationOutput:
    """
    Convert Document to NavigationOutput.

    Works with both old and new metadata structures.
    """
    metadata = document.metadata

    # Extract fields with fallbacks
    page_id = metadata.get("page_id", "")
    page_title = metadata.get("title", "Bilinmeyen Sayfa")

    # URL: try new structure first, fallback to old
    url = metadata.get("url") or metadata.get("url_route", "")

    category = metadata.get("category", "unknown")

    # Check if sub page (old structure)
    is_sub_page = metadata.get("document_type") == "sub_page"
    sub_page_type = metadata.get("sub_page_type") if is_sub_page else None
    parent_page_id = metadata.get("parent_page_id") if is_sub_page else None
    parent_page_title = metadata.get("main_page_title") if is_sub_page else None
    full_path = metadata.get("full_path") if is_sub_page else None

    # Process parameters (handles both old and new structures)
    requires_params, parameters = _process_parameters(metadata)

    # Build user-friendly messages
    suggestion_text = (
        f"Bu alt sayfada {page_title.lower()} ile ilgili işlemlerinizi yapabilirsiniz."
        if is_sub_page
        else f"Bu sayfada {page_title.lower()} ile ilgili işlemlerinizi yapabilirsiniz."
    )

    reasoning = f"{page_title} sayfası kullanıcının isteği için en uygun sayfa olarak belirlendi."
    if is_sub_page:
        reasoning += f" Ana sayfa: {parent_page_title}"

    # Add catalog version info if available
    catalog_version = metadata.get("catalog_version")
    if catalog_version:
        logger.debug(f"[FORZA] Using catalog version: {catalog_version}")

    return NavigationOutput(
        page_id=page_id,
        page_title=page_title,
        url=url,
        category=category,
        is_sub_page=is_sub_page,
        sub_page_type=sub_page_type,
        parent_page_id=parent_page_id,
        parent_page_title=parent_page_title,
        full_path=full_path,
        requires_parameters=requires_params,
        parameters=parameters,
        confidence=0.85,
        reasoning=reasoning,
        suggestion_text=suggestion_text,
        cta_text="Parametreleri Girin" if requires_params else "Sayfaya Git",
        alternative_suggestions=None
    )


def _process_parameters(metadata: Dict[str, Any]) -> tuple:
    """
    Process URL parameters from metadata.

    Supports both old and new metadata structures:
    - New: has_parameters (bool), parameter_count (int)
    - Old: has_url_parameters ("yes"/"no"), url_parameters (JSON string)
    """
    parameters = None

    # Check new structure first
    has_params = metadata.get("has_parameters", False)

    # Fallback to old structure
    if not has_params:
        has_params = metadata.get("has_url_parameters", "no") == "yes"

    # Extract parameter details if available
    if has_params:
        # Try old structure (url_parameters as JSON string)
        if metadata.get("url_parameters"):
            try:
                url_params = _parse_url_parameters(metadata.get("url_parameters"))
                if url_params:
                    parameters = {}
                    for param_name, param_info in url_params.items():
                        parameters[param_name] = {
                            "name": param_name,
                            "type": param_info.get("type", "string"),
                            "description": param_info.get("description", ""),
                            "required": param_info.get("required", False),
                            "default": param_info.get("default"),
                        }
            except Exception as e:
                logger.warning(f"[FORZA] Error processing parameters: {e}")

        # If no parameters extracted but has_parameters is true,
        # extract from URL placeholders
        if not parameters:
            url = metadata.get("url") or metadata.get("url_route", "")
            if url and "{" in url and "}" in url:
                # Extract parameter names from URL
                import re
                param_names = re.findall(r'\{(\w+)\}', url)
                if param_names:
                    parameters = {}
                    for param_name in param_names:
                        # Skip base_url placeholders
                        if _is_base_url_parameter(param_name):
                            continue

                        parameters[param_name] = {
                            "name": param_name,
                            "type": "string",
                            "description": f"URL parameter: {param_name}",
                            "required": True,
                            "default": None,
                        }

    return has_params, parameters
