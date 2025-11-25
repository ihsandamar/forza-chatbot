"""
Dependency Injection Container

Creates and wires all dependencies according to the ARCHITECTURE.md.
This is the single place where all components are instantiated and configured.

Usage:
    config = Config.from_env()
    chat_service = create_chatbot_dependencies(config)
    # Use chat_service with interfaces
"""

from typing import Optional

from src.core.models import ChatbotConfig, AssistantConfig
from src.core.config import Config
from src.core.chatbot import Chatbot
from src.core.session_manager import SessionManager
from src.core.conversation import ConversationManager
from src.core.assistant_manager import AssistantManager
from src.api.chat_service import ChatService
from src.models.llm import LLM
from src.graphs.graph_repository import GraphRepository


def create_chatbot_dependencies(
    config: Optional[ChatbotConfig] = None
) -> ChatService:
    """
    Create all dependencies and wire them together.

    This is the DI container. It creates:
    1. LLM instance
    2. Graph instance
    3. Chatbot instance
    4. Manager instances (Session, Conversation, Assistant)
    5. ChatService (orchestration layer)

    Args:
        config: ChatbotConfig instance. If None, loads from environment.

    Returns:
        ChatService instance ready to use

    Raises:
        ValueError: If configuration is invalid
        Exception: If any dependency creation fails

    Example:
        # Using default config from environment
        chat_service = create_chatbot_dependencies()

        # Or with explicit config
        config = ChatbotConfig(
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            llm_temperature=0.0,
            llm_api_key="sk-...",
            graph_name="default",
            graph_config={},
            system_prompt="You are helpful assistant",
            assistant_name="Assistant"
        )
        chat_service = create_chatbot_dependencies(config)
    """

    # 1. Load/validate configuration
    if config is None:
        try:
            # Try to load from YAML first
            config = Config.from_yaml("config/config.yaml")
        except FileNotFoundError:
            # Fall back to environment variables
            config = Config.from_env()

    # Validate configuration
    errors = Config.validate(config)
    if errors:
        raise ValueError(f"Configuration errors: {errors}")

    # 2. Create LLM
    llm = LLM(
        provider=config.llm_provider,
        model=config.llm_model,
        temperature=config.llm_temperature,
        api_key=config.llm_api_key,
        base_url=config.llm_base_url
    )

    # 3. Create Graph
    graph_repo = GraphRepository(llm)
    graph = graph_repo.get(config.graph_name)

    # 4. Create Chatbot
    assistant_config = AssistantConfig(
        system_prompt=config.system_prompt,
        assistant_name=config.assistant_name
    )

    chatbot = Chatbot(
        llm=llm.get_chat(),  # Get the LangChain chat instance
        graph=graph,
        config=config.graph_config,
        assistant_config=assistant_config
    )

    # 5. Create Managers
    session_mgr = SessionManager()
    conv_mgr = ConversationManager()
    assistant_mgr = AssistantManager(assistant_config)

    # 6. Create Service (Orchestration layer)
    chat_service = ChatService(
        chatbot=chatbot,
        session_manager=session_mgr,
        conversation_manager=conv_mgr,
        assistant_manager=assistant_mgr
    )

    return chat_service


__all__ = ["create_chatbot_dependencies"]
