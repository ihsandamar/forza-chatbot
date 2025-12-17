"""
Chat Assistant Configuration.

Configuration model for chat assistant with future extensibility.
"""
from pydantic import Field
from src.models.base_assistant_configuration import BaseAssistantConfiguration


class ChatAssistantConfiguration(BaseAssistantConfiguration):
    """
    Configuration for Chat Assistant.

    Extends BaseAssistantConfiguration with chat-specific settings.
    Currently uses only base configuration, but designed for future extensibility.

    Future possible additions:
    - temperature: float
    - max_tokens: int
    - enable_tools: bool
    - tool_choice: str
    """

    # Chat-specific configuration (currently none, but ready for future)
    # Example for future:
    # temperature: float = Field(
    #     default=0.7,
    #     description="Sohbet için LLM sıcaklık ayarı"
    # )

    pass
