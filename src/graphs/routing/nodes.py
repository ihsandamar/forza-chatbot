"""
Routing Graph Node Implementations.

Simple document retrieval node based on forza_routing_graph.py
"""

import logging
from typing import Optional
from langchain_chroma import Chroma
from langchain_core.messages import HumanMessage, AnyMessage

from .states import RoutingState

logger = logging.getLogger(__name__)


def normalize_messages_to_message(state: RoutingState) -> RoutingState:
    """
    Normalize messages list to a single message.

    Extracts the last message from the messages list and converts it to
    a HumanMessage if necessary. Sets the 'message' field in the state.

    Args:
        state: Current routing state with messages list.

    Returns:
        Updated state with normalized message field.
    """
    try:
        logger.info("[ROUTING] Normalizing messages to single message")

        # Get messages list
        messages = state.get("messages", [])
        logger.debug(f"[ROUTING] Messages count: {len(messages)}")

        if not messages:
            logger.warning("[ROUTING] No messages in state")
            state["message"] = None
            return state

        # Get the last message
        last_msg = messages[-1]
        logger.debug(f"[ROUTING] Last message type: {type(last_msg).__name__}")

        # Convert to HumanMessage if needed
        if isinstance(last_msg, HumanMessage):
            # Already a HumanMessage
            state["message"] = last_msg
            logger.debug("[ROUTING] Message is already HumanMessage")

        elif isinstance(last_msg, dict):
            # Dict format: {"content": "...", "role": "user", ...}
            content = last_msg.get("content", "")
            state["message"] = HumanMessage(content=content)
            logger.debug(f"[ROUTING] Converted dict message to HumanMessage (content: '{content[:50]}...')")

        elif isinstance(last_msg, str):
            # String format
            state["message"] = HumanMessage(content=last_msg)
            logger.debug(f"[ROUTING] Converted string message to HumanMessage (content: '{last_msg[:50]}...')")

        elif isinstance(last_msg, AnyMessage):
            # Other LangChain message types
            content = getattr(last_msg, "content", str(last_msg))
            state["message"] = HumanMessage(content=str(content))
            logger.debug(f"[ROUTING] Converted {type(last_msg).__name__} to HumanMessage")

        else:
            # Unknown type - convert to string
            content = str(last_msg)
            state["message"] = HumanMessage(content=content)
            logger.debug(f"[ROUTING] Converted {type(last_msg).__name__} to HumanMessage (as string)")

        logger.info(f"[ROUTING] Message normalized successfully: '{state['message'].content[:50]}...'")
        return state

    except Exception as e:
        logger.error(f"[ROUTING] Message normalization failed: {e}", exc_info=True)
        state["message"] = None
        return state


def document_retrieval_node(state: RoutingState, vectorstore: Optional[Chroma]) -> RoutingState:
    """
    Retrieve relevant documents based on user input.

    Processes a single message from the state and performs similarity search.

    Args:
        state: Current routing state with message.
        vectorstore: Chroma vectorstore for similarity search.

    Returns:
        Updated state with related_pages.
    """
    try:
        logger.info(f"[ROUTING] Document retrieval started")
        logger.debug(f"[ROUTING] Vectorstore available: {vectorstore is not None}")

        # Get the normalized message from state
        message = state.get("message")

        # Validate message exists
        if not message:
            logger.warning("[ROUTING] No message in state")
            state["related_pages"] = []
            return state

        # Message should already be normalized to HumanMessage by normalize_messages_to_message node
        if not isinstance(message, HumanMessage):
            logger.error(f"[ROUTING] Message is not a HumanMessage, type: {type(message).__name__}")
            state["related_pages"] = []
            return state

        # Extract content from message
        user_input = message.content.strip() if isinstance(message.content, str) else ""
        logger.info(f"[ROUTING] User input: '{user_input}'")

        # Validate inputs
        if not user_input:
            logger.warning("[ROUTING] Empty user input")
            state["related_pages"] = []
            return state

        if not vectorstore:
            logger.error("[ROUTING] Vectorstore not available - vectorstore is None")
            logger.debug("[ROUTING] Check vectorstore setup in RoutingGraph._setup_vectorstore()")
            state["related_pages"] = []
            return state

        # Similarity search - get top 5
        logger.debug("[ROUTING] Executing similarity_search...")
        retrieved_docs = vectorstore.similarity_search(user_input, k=5)

        if not retrieved_docs:
            logger.warning("[ROUTING] No documents found")
            state["related_pages"] = []
            return state

        # Assign scores (1.0, 0.9, 0.8, 0.7, 0.6)
        docs_with_scores = [
            (doc, 1.0 - (i * 0.1))
            for i, doc in enumerate(retrieved_docs)
        ]

        state["related_pages"] = docs_with_scores

        # Log results
        logger.info(f"[ROUTING] Found {len(retrieved_docs)} documents")
        for i, (doc, score) in enumerate(docs_with_scores):
            title = doc.metadata.get("title", "Unknown") if doc.metadata else "Unknown"
            logger.debug(f"[ROUTING] {i+1}. {title} (score: {score:.2f})")

    except Exception as e:
        logger.error(f"[ROUTING] Document retrieval failed: {e}", exc_info=True)
        state["related_pages"] = []

    return state
