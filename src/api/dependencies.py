from functools import lru_cache
from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.models.llm import LLM
from src.services.config_loader import ConfigLoader
from src.services.container import ServiceContainer
from src.graphs.graph_repository import GraphRepository
from src.builders.chatbot_builder import ChatbotBuilder
from src.builders.dependency_factory import DependencyFactory
from src.builders.adapter_factory import AdapterFactory
from src.factories.llm_factory import LLMFactory


# Singleton instances
_chat_service_instance = None
_chatbot_instance = None


def get_chatbot() -> Chatbot:
    """
    Dependency to get Chatbot instance

    Returns:
        Chatbot: Singleton instance of chatbot
    """
    global _chatbot_instance
    if _chatbot_instance is None:
        # Load config
        config = ConfigLoader.load_config("config/config.yaml")

        # Create builders with config
        dependency_factory = DependencyFactory(config=config)
        adapter_factory = AdapterFactory()

        # Build chatbot
        _chatbot_instance = (
            ChatbotBuilder(dependency_factory, adapter_factory)
            .with_model(
                config.llm.model,
                config.llm.temperature,
                config.llm.api_key,
                config.llm.provider,
                config.llm.base_url
            )
            .with_graph(config.chatbot.graph_type)
            .with_graph_config({"configurable": {"thread_id": config.chatbot.thread_id}})
            .with_assistant_configuration(getattr(config, 'sql_agent_configuration', None))
            .build()
        )

    return _chatbot_instance


def get_chat_service() -> ChatService:
    """
    Dependency to get ChatService instance

    Returns:
        ChatService: Singleton instance of chat service
    """
    global _chat_service_instance
    if _chat_service_instance is None:
        chatbot = get_chatbot()
        _chat_service_instance = ChatService(chatbot)
    return _chat_service_instance
