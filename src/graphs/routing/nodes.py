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


def extract_user_input_node(state: NavigationState) -> NavigationState:
    """Extract user input from last HumanMessage in messages."""
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
        return state

    except UserInputExtractionError:
        raise
    except Exception as e:
        logger.error(f"[FORZA] Unexpected error extracting user input: {e}", exc_info=True)
        raise UserInputExtractionError(f"Failed to extract user input: {str(e)}") from e


def find_documents_node(
    state: NavigationState, vectorstore: Optional[Chroma] = None
) -> NavigationState:
    """Retrieve similar documents using vectorstore."""
    try:
        if not vectorstore:
            logger.error("[FORZA] Vectorstore not available")
            raise VectorStoreNotFoundError("Vectorstore is not initialized")

        user_input = state.get("user_input", "")
        if not user_input:
            logger.error("[FORZA] Empty user input for document retrieval")
            raise DocumentRetrievalError("User input is empty or missing")

        retrieved_docs = vectorstore.similarity_search(user_input, k=SIMILARITY_SEARCH_K)

        if not retrieved_docs:
            logger.error("[FORZA] No documents found for user input")
            raise DocumentRetrievalError(f"No similar documents found for query: {user_input[:100]}")

        # Assign scores (default scoring since vectorstore doesn't return scores)
        docs_with_scores = [
            (doc, 1.0 - (i * 0.1)) for i, doc in enumerate(retrieved_docs)
        ]

        state["related_pages"] = docs_with_scores
        logger.info(f"[FORZA] Retrieved {len(retrieved_docs)} documents")
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
    """Check if page has URL parameters."""
    try:
        doc = state.get("most_related_document")
        if not doc:
            logger.error("[FORZA] No most_related_document found in state")
            raise ParameterDetectionError("most_related_document is missing from state")

        metadata = doc.metadata or {}
        url_params = _parse_url_parameters(metadata.get("url_parameters", {}))

        has_params = bool(url_params and len(url_params) > 0)
        state["has_parameters"] = has_params

        logger.debug(f"[FORZA] Page has parameters: {has_params}")
        return state

    except ParameterDetectionError:
        raise
    except Exception as e:
        logger.error(f"[FORZA] Unexpected error detecting parameters: {e}", exc_info=True)
        raise ParameterDetectionError(f"Parameter detection failed: {str(e)}") from e


def extract_page_parameters_node(
    state: NavigationState, llm: LLM, config: Any
) -> NavigationState:
    """Extract URL parameters using tools."""
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
        url_params = _parse_url_parameters(metadata.get("url_parameters"))

        if not url_params:
            logger.error("[FORZA] No URL parameters found in document metadata")
            raise ParameterExtractionError("URL parameters not found in document metadata")

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
    """Update URL with filled parameters."""
    try:
        doc = state.get("most_related_document")
        if not doc:
            logger.error("[FORZA] No most_related_document found for URL update")
            raise URLUpdateError("most_related_document is missing from state")

        metadata = doc.metadata
        if not metadata:
            logger.error("[FORZA] Document metadata is missing")
            raise URLUpdateError("Document metadata is missing")

        original_url = metadata.get("url_route", "")
        if not original_url:
            logger.error("[FORZA] URL route not found in document metadata")
            raise URLUpdateError("URL route not found in document metadata")

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

        # Apply baseUrl
        from src.services.config_loader import ConfigLoader
        config = ConfigLoader.load_config("config/config.yaml")
        web_site_url = config.forza.web_site_url
        updated_url = updated_url.replace("{baseUrl}", web_site_url)

        # Update document if URL changed
        if updated_url != original_url:
            updated_metadata = metadata.copy()
            updated_metadata["url_route"] = updated_url
            updated_metadata["original_url"] = original_url

            state["most_related_document"] = Document(
                page_content=doc.page_content,
                metadata=updated_metadata
            )
            logger.debug(f"[FORZA] URL updated: {original_url} -> {updated_url}")

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


def find_alternative_pages_node(state: NavigationState) -> NavigationState:
    """Find alternative pages when parameters cannot be filled."""
    try:
        retry_count = state.get("retry_count", 0)
        if retry_count >= MAX_RETRIES:
            logger.warning(f"[FORZA] Max retries ({MAX_RETRIES}) reached")
            state["no_more_alternatives"] = True
            state["tool_results_valid"] = True
            return state

        related_pages = state.get("related_pages", [])
        if not related_pages:
            logger.warning("[FORZA] No related pages available for alternatives")
            state["no_more_alternatives"] = True
            state["tool_results_valid"] = True
            return state

        current_doc = state.get("most_related_document")
        current_page_id = current_doc.metadata.get("page_id") if current_doc else None

        tried_pages = state.get("tried_page_ids", set())
        if current_page_id:
            tried_pages.add(current_page_id)

        # Find next untried alternative
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

        if not found_alternative:
            logger.warning("[FORZA] No more alternative pages available to try")
            state["tried_page_ids"] = tried_pages
            state["no_more_alternatives"] = True
            state["tool_results_valid"] = True

        return state

    except Exception as e:
        logger.error(f"[FORZA] Unexpected error during alternative page search: {e}", exc_info=True)
        state["no_more_alternatives"] = True
        state["tool_results_valid"] = True
        return state


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _parse_url_parameters(url_parameters: Any) -> Optional[Dict[str, Any]]:
    """Parse URL parameters from various formats."""
    if isinstance(url_parameters, str):
        try:
            return json.loads(url_parameters)
        except json.JSONDecodeError:
            logger.warning(f"[FORZA] Invalid JSON in url_parameters: {url_parameters}")
            return None
    return url_parameters or {}


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
                logger.debug(f"[FORZA] Tool '{tool_name}' executed successfully")
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

Tool sonuçlarından KULLANICI İSTEĞİNE EN UYGUN değeri seç ve bu formatta JSON döndür:

{{
  "parametre_ismi": {{
    "parameter_name": "parametre_ismi",
    "value": "id_değeri",
    "display_name": "görünen_isim"
  }}
}}

KRİTİK KURALLAR:
1. EĞER tool sonuçları boş veya hatalıysa, MUTLAKA boş JSON döndür: {{}}
2. EĞER tool'lardan başarılı sonuç gelmediyse, MUTLAKA boş JSON döndür: {{}}
3. SADECE başarılı tool sonucu varsa parametre doldur
4. Tool sonuçlarından kullanıcı isteğine en uygun olanı seç
5. Sadece düz JSON döndür

Sadece JSON döndür:"""

        messages.append(HumanMessage(content=final_prompt))
        final_response = llm.get_chat().invoke(messages)

        # Parse JSON from response
        response_text = (
            final_response.content if hasattr(final_response, "content")
            else str(final_response)
        )

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
            return filled_parameters

        logger.warning("[FORZA] Could not parse JSON from LLM response")
        return {}

    except Exception as e:
        logger.error(f"[FORZA] LLM processing error: {e}")
        traceback.print_exc()
        return {}


def _check_tool_results_validity(messages: list) -> bool:
    """Check if any tool returned valid results."""
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue

        try:
            result = json.loads(msg.content)

            if result.get("status") == "error":
                continue

            data = result.get("data", {})

            # Check for list fields with data
            found_valid_data = False
            for key, value in data.items():
                if isinstance(value, list) and len(value) > 0:
                    logger.debug(f"[FORZA] Found valid tool result with {len(value)} {key}")
                    found_valid_data = True
                    break

            if found_valid_data:
                return True

        except (json.JSONDecodeError, AttributeError, KeyError):
            continue

    logger.warning("[FORZA] No valid tool results found")
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
    """Convert Document to NavigationOutput."""
    metadata = document.metadata

    page_id = metadata.get("page_id", "")
    page_title = metadata.get("title", "Bilinmeyen Sayfa")
    url = metadata.get("url_route", "")
    category = metadata.get("category", "unknown")

    is_sub_page = metadata.get("document_type") == "sub_page"
    sub_page_type = metadata.get("sub_page_type") if is_sub_page else None
    parent_page_id = metadata.get("parent_page_id") if is_sub_page else None
    parent_page_title = metadata.get("main_page_title") if is_sub_page else None
    full_path = metadata.get("full_path") if is_sub_page else None

    requires_params, parameters = _process_parameters(metadata)

    suggestion_text = (
        f"Bu alt sayfada {page_title.lower()} ile ilgili işlemlerinizi yapabilirsiniz."
        if is_sub_page
        else f"Bu sayfada {page_title.lower()} ile ilgili işlemlerinizi yapabilirsiniz."
    )

    reasoning = f"{page_title} sayfası kullanıcının isteği için en uygun sayfa olarak belirlendi."
    if is_sub_page:
        reasoning += f" Ana sayfa: {parent_page_title}"

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
    """Process URL parameters from metadata."""
    has_url_params = metadata.get("has_url_parameters", "no") == "yes"
    parameters = None

    if has_url_params and metadata.get("url_parameters"):
        try:
            url_params = json.loads(metadata.get("url_parameters", "{}"))
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
            has_url_params = False

    return has_url_params, parameters
