"""
Configuration Response Models.

Response models for configuration management endpoints.
Follows SOLID principles with clear data representation.

Uses JSON Schema format for dynamic form generation on frontend.
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class ConfigFieldView(BaseModel):
    """
    View model for a single configuration field with JSON Schema info.

    KISS: Simple field representation with schema metadata.
    """

    schema: Dict[str, Any] = Field(
        description="JSON Schema definition for this field",
        example={
            "type": "string",
            "default": "",
            "description": "Forza API token",
            "title": "Token"
        }
    )

    value: Any = Field(
        description="Current value (masked for sensitive fields)",
        example="your-api-t..."
    )


class LLMConfigView(BaseModel):
    """
    View model for LLM configuration with JSON Schema.

    KISS: Schema + current values structure.
    SRP: Single responsibility - display LLM config.
    """

    schema: Dict[str, Any] = Field(
        description="JSON Schema for LLM configuration",
        example={
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "default": "gpt-4o-mini",
                    "description": "LLM model name"
                },
                "temperature": {
                    "type": "number",
                    "default": 0.7,
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Model temperature"
                }
            }
        }
    )

    values: Dict[str, Any] = Field(
        description="Current configuration values (sensitive data masked)",
        example={
            "model": "gpt-4o-mini",
            "temperature": 0.7,
            "provider": "openai",
            "has_api_key": True
        }
    )


class SubAgentConfigView(BaseModel):
    """
    View model for sub-agent configuration with JSON Schema.

    KISS: Schema + current values structure.
    OCP: Open for extension, closed for modification.
    """

    name: str = Field(
        description="Sub-agent name",
        example="routing"
    )

    agent_type: str = Field(
        description="Type of the agent configuration class",
        example="RoutingAssistantConfiguration"
    )

    schema: Dict[str, Any] = Field(
        description="JSON Schema for this agent's configuration (from model_json_schema)",
        example={
            "type": "object",
            "title": "RoutingAssistantConfiguration",
            "properties": {
                "system_prompt": {
                    "type": "string",
                    "default": "Sen yardımcı bir asistansın.",
                    "description": "System prompt"
                },
                "token": {
                    "type": "string",
                    "default": "",
                    "description": "Forza API token"
                }
            }
        }
    )

    values: Dict[str, Any] = Field(
        description="Current configuration values (sensitive data masked)",
        example={
            "system_prompt": "You are a routing assistant.",
            "has_token": True,
            "token_preview": "your-api-t..."
        }
    )


class ConfigurationView(BaseModel):
    """
    Main view model for runtime configuration.

    KISS: Clear hierarchical structure.
    SRP: Single responsibility - display full configuration.
    """

    graph_type: str = Field(
        description="Current graph type",
        example="supervisor"
    )

    llm: LLMConfigView = Field(
        description="LLM configuration"
    )

    subagents: Dict[str, SubAgentConfigView] = Field(
        description="Sub-agent configurations, keyed by agent name",
        example={
            "routing": {
                "name": "routing",
                "agent_type": "RoutingAssistantConfiguration",
                "system_prompt": "You are a routing assistant.",
                "has_token": True,
                "token_preview": "secret-tok..."
            }
        }
    )

    available_subagent_types: List[str] = Field(
        description="List of available sub-agent types",
        example=["routing", "chat"]
    )

    class Config:
        """Pydantic config."""
        json_schema_extra = {
            "example": {
                "graph_type": "supervisor",
                "llm": {
                    "model": "gpt-4o-mini",
                    "temperature": 0.7,
                    "provider": "openai",
                    "has_api_key": True
                },
                "subagents": {
                    "routing": {
                        "name": "routing",
                        "agent_type": "RoutingAssistantConfiguration",
                        "system_prompt": "You are a routing assistant.",
                        "has_token": True,
                        "token_preview": "your-api-t..."
                    }
                },
                "available_subagent_types": ["routing", "chat"]
            }
        }


class ConfigurationUpdateResponse(BaseModel):
    """
    Response model for configuration update operations.

    KISS: Simple success/error response.
    """

    success: bool = Field(
        description="Whether the update was successful",
        example=True
    )

    message: str = Field(
        description="Human-readable message about the update",
        example="Configuration updated successfully"
    )

    updated_config: ConfigurationView = Field(
        description="The updated configuration"
    )


__all__ = [
    "LLMConfigView",
    "SubAgentConfigView",
    "ConfigurationView",
    "ConfigurationUpdateResponse"
]
