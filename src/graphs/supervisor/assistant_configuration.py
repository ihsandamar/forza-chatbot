"""
Supervisor Assistant Configuration.

LangGraph-compatible configuration with flat fields for Studio UI.
Provides typed helper methods for sub-agent configurations.
"""
from typing import Literal, Annotated
from datetime import datetime
from pydantic import Field
from src.models.base_assistant_configuration import BaseAssistantConfiguration
from src.graphs.routing.assistant_configuration import RoutingAssistantConfiguration
from src.graphs.chat.assistant_configuration import ChatAssistantConfiguration

today = datetime.now().strftime("%Y-%m-%d")


class SupervisorAssistantConfiguration(BaseAssistantConfiguration):
    """
    Configuration for Supervisor Assistant.

    Architecture:
    - Flat fields for LangGraph Studio compatibility
    - json_schema_extra for node-specific configuration
    - Helper methods convert flat fields to typed configs
    - SOLID principles through separation of concerns

    LangGraph Studio will display each field with node mapping,
    while Python code uses typed configuration classes.

    Benefits:
    - ✅ LangGraph Studio compatible (flat fields)
    - ✅ Type-safe (helper methods return typed configs)
    - ✅ SOLID (separate config classes exist)
    - ✅ KISS (simple, clear structure)
    """

    # ========================================
    # Routing Sub-Agent Configuration
    # ========================================
    routing_token: str = Field(
        default="",
        description="Forza API token for routing agent",
        json_schema_extra={"langgraph_nodes": ["routing"]}
    )

    routing_system_prompt: str = Field(
        default="Sen Forza navigasyon asistanısın. Kullanıcıları doğru sayfalara yönlendirirsin.",
        description="System prompt for routing sub-agent",
        json_schema_extra={"langgraph_nodes": ["routing"], "langgraph_type": "prompt"}
    )

    routing_model: Annotated[
        Literal[
            "anthropic:claude-haiku-4-5",
            "anthropic:claude-sonnet-4-5",
            "openai:gpt-5",
            "openai:gpt-5-mini"
        ],
        {"__template_metadata__": {"kind": "llm"}},
    ] = Field(
        default="anthropic:claude-haiku-4-5",
        description="Language model for routing sub-agent",
        json_schema_extra={"langgraph_nodes": ["routing"]},
    )

    # ========================================
    # Chat Sub-Agent Configuration
    # ========================================
    chat_system_prompt: str = Field(
        default="Sen yardımcı bir sohbet asistanısın. Kullanıcılarla doğal ve samimi bir şekilde konuşursun.",
        description="System prompt for chat sub-agent",
        json_schema_extra={"langgraph_nodes": ["chat"], "langgraph_type": "prompt"}
    )

    chat_model: Annotated[
        Literal[
            "anthropic:claude-haiku-4-5",
            "anthropic:claude-sonnet-4-5",
            "openai:gpt-5",
            "openai:gpt-5-mini"
        ],
        {"__template_metadata__": {"kind": "llm"}},
    ] = Field(
        default="anthropic:claude-haiku-4-5",
        description="Language model for chat sub-agent",
        json_schema_extra={"langgraph_nodes": ["chat"]},
    )

    # ========================================
    # Helper Methods (Convert flat → typed)
    # ========================================
    def get_routing_config(self) -> RoutingAssistantConfiguration:
        """
        Convert flat routing fields to typed RoutingAssistantConfiguration.

        Returns:
            RoutingAssistantConfiguration with values from flat fields
        """
        return RoutingAssistantConfiguration(
            token=self.routing_token,
            system_prompt=self.routing_system_prompt,
            assistant_name="RoutingAssistant"
        )

    def get_chat_config(self) -> ChatAssistantConfiguration:
        """
        Convert flat chat fields to typed ChatAssistantConfiguration.

        Returns:
            ChatAssistantConfiguration with values from flat fields
        """
        return ChatAssistantConfiguration(
            system_prompt=self.chat_system_prompt,
            assistant_name="ChatAssistant"
        )
