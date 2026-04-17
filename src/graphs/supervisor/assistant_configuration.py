"""
Supervisor Assistant Configuration.

LangGraph-compatible configuration with flat fields for Studio UI.
Provides typed helper methods for sub-agent configurations.
"""
from typing import Literal, Annotated, List, Dict, Any
from datetime import datetime
from pydantic import Field
from src.models.base_assistant_configuration import BaseAssistantConfiguration
from src.graphs.routing.assistant_configuration import RoutingAssistantConfiguration
from src.graphs.chat.assistant_configuration import ChatAssistantConfiguration
from src.graphs.report_agent.assistant_configuration import GenericSQLAssistantConfiguration
from src.graphs.report_agent.configuration import ReportAgentConfiguration

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
            "",                           # Use global LLM (default)
            "openai:gpt-4.1",
            "openai:gpt-4.1-mini",
            "anthropic:claude-haiku-4-5",
            "anthropic:claude-sonnet-4-5",
            "openai:gpt-5",
            "openai:gpt-5-mini"
        ],
        {"__template_metadata__": {"kind": "llm"}},
    ] = Field(
        default="",
        description="Language model for routing sub-agent (empty = use global LLM)",
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
            "",                           # Use global LLM (default)
            "openai:gpt-4.1",
            "openai:gpt-4.1-mini",
            "anthropic:claude-haiku-4-5",
            "anthropic:claude-sonnet-4-5",
            "openai:gpt-5",
            "openai:gpt-5-mini"
        ],
        {"__template_metadata__": {"kind": "llm"}},
    ] = Field(
        default="",
        description="Language model for chat sub-agent (empty = use global LLM)",
        json_schema_extra={"langgraph_nodes": ["chat"]},
    )

    # ========================================
    # Report Sub-Agent Configuration
    # ========================================
    report_name: str = Field(
        default="",
        description="Rapor adı (report agent için)",
        json_schema_extra={"langgraph_nodes": ["report"]}
    )

    report_description: str = Field(
        default="",
        description="Rapor açıklaması",
        json_schema_extra={"langgraph_nodes": ["report"]}
    )

    report_table_name: str = Field(
        default="MasterReportDocumentTable",
        description="Sorgunun uygulanacağı tablo adı",
        json_schema_extra={"langgraph_nodes": ["report"]}
    )

    report_query: str = Field(
        default=ReportAgentConfiguration.model_fields["query"].default,
        description="Tablo oluşturma SQL sorgusu (runtime'da çalıştırılacak)",
        json_schema_extra={"langgraph_nodes": ["report"]}
    )

    report_column_metadata: Dict[str, str] = Field(
        default=ReportAgentConfiguration.model_fields["column_metadata"].default,
        description="Sütun metaverileri - column_name -> description mapping",
        json_schema_extra={"langgraph_nodes": ["report"]}
    )

    report_business_rules: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="İş kuralları JSON formatında",
        json_schema_extra={"langgraph_nodes": ["report"]}
    )

    report_system_prompt: str = Field(
        default="Sen bir ERP uzmanı ve SQL sorgulama asistanısın.",
        description="System prompt for report sub-agent",
        json_schema_extra={"langgraph_nodes": ["report"], "langgraph_type": "prompt"}
    )

    report_model: Annotated[
        Literal[
            "",                           # Use global LLM (default)
            "openai:gpt-4.1",
            "openai:gpt-4.1-mini",
            "anthropic:claude-haiku-4-5",
            "anthropic:claude-sonnet-4-5",
            "openai:gpt-5",
            "openai:gpt-5-mini"
        ],
        {"__template_metadata__": {"kind": "llm"}},
    ] = Field(
        default="",
        description="Language model for report sub-agent (empty = use global LLM)",
        json_schema_extra={"langgraph_nodes": ["report"]},
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

    def get_report_config(self) -> GenericSQLAssistantConfiguration:
        """
        Convert flat report fields to typed GenericSQLAssistantConfiguration.

        Returns:
            GenericSQLAssistantConfiguration with values from flat fields
        """
        return GenericSQLAssistantConfiguration(
            report_name=self.report_name,
            description=self.report_description,
            table_name=self.report_table_name,
            query=self.report_query,
            column_metadata=self.report_column_metadata,
            business_rules=self.report_business_rules,
            system_prompt=self.report_system_prompt,
            assistant_name="ReportAssistant"
        )
