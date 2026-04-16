# src/launch/_chat_service.py
"""
Unified ChatService factory — used by all launchers.

This replaces src/di_container.py.
Canonical ChatService: src/api/services/chat_service.py
"""
from src.core.app_config import get_config
from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.models.llm import LLM
from src.graphs.graph_repository import GraphRepository


def build_chat_service(config=None) -> ChatService:
    """
    Build and return a fully wired ChatService.

    Args:
        config: Config object from get_config(). If None, get_config() is called.

    Returns:
        ChatService instance backed by the LLM and graph specified in config.
    """
    if config is None:
        config = get_config()

    llm = LLM(
        provider=config.llm.provider,
        model=config.llm.model,
        temperature=config.llm.temperature,
        api_key=config.llm.api_key,
        base_url=getattr(config.llm, "base_url", None),
    )
    graph = GraphRepository(llm).get(config.chatbot.graph_type)
    chatbot = Chatbot(llm=llm.get_chat(), graph=graph)
    return ChatService(chatbot=chatbot)
