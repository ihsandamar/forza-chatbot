"""
Routing Graph Node Implementations.

Simple document retrieval node based on forza_routing_graph.py
"""

import logging
from typing import Optional
from flask import json
from langchain_chroma import Chroma
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from src.graphs.chat import state
from src.graphs.routing.exceptions import DocumentRetrievalError, MessageNotFoundError, RotuingAgentBaseException, VectorStoreNotFoundError

from .states import RoutingState

logger = logging.getLogger(__name__)




def find_similar_documents_node(state: RoutingState, vectorstore: Optional[Chroma]) -> RoutingState:

    if not vectorstore:
        raise VectorStoreNotFoundError()
    
    try:
        # Get the normalized message from state
        message = state.get("message")

        # Validate message exists
        if not message:
            raise MessageNotFoundError()
        
        # Message should already be normalized to HumanMessage by normalize_messages_to_message node
        if not isinstance(message, HumanMessage):
            raise MessageNotFoundError("Message in state is not a HumanMessage.")

        # Extract content from message
        user_input = message.content.strip() if isinstance(message.content, str) else ""

        # Similarity search - get top 5
        retrieved_docs = vectorstore.similarity_search(user_input, k=5)

        if not retrieved_docs:
            raise DocumentRetrievalError("No similar documents found.")

        state["similar_documents"] = retrieved_docs


        for i, doc in enumerate(retrieved_docs):
            title = doc.metadata.get("title", "Unknown") if doc.metadata else "Unknown"

    except Exception as e:
        raise RotuingAgentBaseException(f"Document retrieval failed: {e}") from e
    return state


def get_most_relevant_document(state: RoutingState) -> Optional[str]:
    """Select the highest scoring document"""

    # Get the first (highest score) document
    most_related_document, score = state["related_pages"][0]
    state["most_related_document"] = most_related_document
    
    return state


def routing_page_has_parameter(state: RoutingState, parameter: str) -> bool:
    """
    Check if the routing state has a specific parameter.

    Args:
        state: Current routing state.
        parameter: Parameter name to check.
    Returns:
        "True" if parameter exists, else "False".
    return parameter in state and state[parameter] is not None
    """

    metadata = state["most_related_document"].metadata
    url_parameters = metadata.get("url_parameters", {})

    if isinstance(url_parameters, str):
        try:
            return json.loads(url_parameters)
        except json.JSONDecodeError:
            print(f"[ERROR] Invalid JSON in url_parameters: {url_parameters}")
            return None
    
    has_params = bool(url_parameters and len(url_parameters) > 0)

    return has_params


def get_routing_page_parameters(state: RoutingState) -> RoutingState:
    """
    Extract URL parameters from the most relevant document in the routing state.

    Args:
        state: Current routing state.
    Returns:
        Updated state with 'routing_page_parameters' field.
    """

    metadata = state["most_relevant_page"].metadata
    url_parameters = metadata.get("url_parameters", {})

    if isinstance(url_parameters, str):
        try:
            url_parameters = json.loads(url_parameters)
        except json.JSONDecodeError:
            logger.error(f"[ROUTING] Invalid JSON in url_parameters: {url_parameters}")
            url_parameters = {}

    state["routing_page_parameters"] = url_parameters

    return state


