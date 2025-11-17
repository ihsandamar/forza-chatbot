from functools import lru_cache
from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.models.llm import LLM
from src.services.config_loader import ConfigLoader
from src.services.container import ServiceContainer
from src.graphs.graph_repository import GraphRepository
from src.builders.chatbot_builder import ChatbotBuilder


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

        # Create container
        container = ServiceContainer()

        # Register LLM
        llm_config = config.llm
        container.register("llm", lambda: LLM(
            model=llm_config.model,
            temperature=llm_config.temperature,
            api_key=llm_config.api_key
        ))

        # Register graph repository
        container.register("graph_repo", lambda: GraphRepository(container.resolve("llm")))

        # Build chatbot
        _chatbot_instance = (
            ChatbotBuilder(container)
            .with_model(llm_config.model, llm_config.temperature, llm_config.api_key)
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
