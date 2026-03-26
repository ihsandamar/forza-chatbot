from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.models.llm import LLM
from src.graphs.graph_entrypoints import supervisor_graph, _get_config


# Singleton instances
_chat_service_instance = None
_chatbot_instance = None


def get_chatbot() -> Chatbot:
    """
    Dependency to get Chatbot instance.

    Uses graph_entrypoints.supervisor_graph() directly — same code path as LangGraph dev.

    Returns:
        Chatbot: Singleton instance of chatbot
    """
    global _chatbot_instance
    if _chatbot_instance is None:
        config = _get_config()

        # LLM: Chatbot wrapper metadata için (get_config_for_ui).
        # supervisor_graph() kendi LLM instance'ını dahili oluşturur.
        llm = LLM(
            provider=config.llm.provider,
            model=config.llm.model,
            temperature=config.llm.temperature,
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
        )

        # LangGraph dev ile birebir aynı kod yolu.
        # Kasıtlı olarak supervisor_graph() hardcode edilmiştir —
        # config.yaml: graph_type=supervisor, bu FastAPI deployment'ı supervisor-only'dir.
        compiled = supervisor_graph()

        _chatbot_instance = Chatbot(
            llm=llm,
            graph=compiled,
            config={"configurable": {"thread_id": "1"}},  # ChatService runtime'da session_id ile override eder
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
