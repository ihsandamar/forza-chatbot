# src/api/dependencies.py
from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.core.runtime_agent_settings import RuntimeAgentSettings
from src.models.llm import LLM
from src.graphs.graph_entrypoints import supervisor_graph, _get_config
from src.graphs.supervisor.assistant_configuration import SupervisorAssistantConfiguration


# Singleton instances
_chat_service_instance = None
_chatbot_instance = None


def get_chatbot() -> Chatbot:
    """
    Dependency to get Chatbot instance.

    Uses graph_entrypoints.supervisor_graph() directly — same code path as LangGraph dev.
    RuntimeAgentSettings is initialised from SupervisorAssistantConfiguration defaults,
    so GET /api/configuration works from the first request.

    Returns:
        Chatbot: Singleton instance
    """
    global _chatbot_instance
    if _chatbot_instance is None:
        config = _get_config()

        llm = LLM(
            provider=config.llm.provider,
            model=config.llm.model,
            temperature=config.llm.temperature,
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
        )

        compiled = supervisor_graph()

        _chatbot_instance = Chatbot(
            llm=llm,
            graph=compiled,
            config={"configurable": {"thread_id": "1"}},
            runtime_agent_settings=RuntimeAgentSettings.from_supervisor_config(
                SupervisorAssistantConfiguration()
            ),
        )

    return _chatbot_instance


def get_chat_service() -> ChatService:
    """
    Dependency to get ChatService instance.

    Returns:
        ChatService: Singleton instance
    """
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService(get_chatbot())
    return _chat_service_instance
