"""
Configuration Request Models.

Request models for configuration management endpoints.
Follows SOLID principles with clear separation of concerns.
"""
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class LLMConfigUpdateRequest(BaseModel):
    """
    Request model for updating LLM configuration.

    KISS: Simple, focused on LLM-specific settings only.
    SRP: Single responsibility - LLM configuration.
    """

    model: Optional[str] = Field(
        default=None,
        description="LLM model name (e.g., 'gpt-4o-mini', 'claude-sonnet-4-5')",
        example="gpt-4o-mini"
    )

    temperature: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Model temperature for response generation",
        example=0.7
    )

    api_key: Optional[str] = Field(
        default=None,
        description="API key for the LLM provider",
        example="sk-..."
    )

    provider: Optional[str] = Field(
        default=None,
        description="LLM provider name (e.g., 'openai', 'anthropic')",
        example="openai"
    )

    base_url: Optional[str] = Field(
        default=None,
        description="Custom base URL for API calls",
        example="https://api.openai.com/v1"
    )


class SubAgentConfigUpdateRequest(BaseModel):
    """
    Request model for updating sub-agent configuration.

    KISS: Generic structure that works for any sub-agent.
    OCP: Open for extension (new agents), closed for modification.
    """

    system_prompt: Optional[str] = Field(
        default=None,
        description="System prompt for the sub-agent",
        example="You are a helpful routing assistant."
    )

    token: Optional[str] = Field(
        default=None,
        description="Authentication token for the sub-agent (e.g., API token)",
        example="secret-token-123"
    )

    # Additional fields can be added here without breaking existing code
    extra_params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional agent-specific parameters"
    )


class ConfigurationUpdateRequest(BaseModel):
    """
    Main request model for updating runtime configuration.

    KISS: Clear structure with optional nested updates.
    SRP: Single responsibility - configuration updates.
    """

    llm: Optional[LLMConfigUpdateRequest] = Field(
        default=None,
        description="LLM configuration updates"
    )

    subagents: Optional[Dict[str, SubAgentConfigUpdateRequest]] = Field(
        default=None,
        description="Sub-agent configuration updates, keyed by agent name (e.g., 'routing', 'chat')",
        example={
            "routing": {
                "token": "new-token",
                "system_prompt": "You are a routing assistant."
            },
            "chat": {
                "system_prompt": "You are a chat assistant."
            }
        }
    )

    class Config:
        """Pydantic config."""
        json_schema_extra = {
            "example": {
                "llm": {
                    "model": "gpt-4o-mini",
                    "temperature": 0.7
                },
                "subagents": {
                    "routing": {
                        "token": "your-api-token",
                        "system_prompt": "You are a routing assistant."
                    }
                }
            }
        }


__all__ = [
    "LLMConfigUpdateRequest",
    "SubAgentConfigUpdateRequest",
    "ConfigurationUpdateRequest"
]
