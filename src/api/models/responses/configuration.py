"""
Configuration Response Models.

Simplified: subagents only, no LLM section.
"""
from typing import Optional, Dict, List
from pydantic import BaseModel, Field


class SubAgentConfigView(BaseModel):
    """View model for one sub-agent's runtime settings."""

    name: str = Field(description="Sub-agent name", example="routing")

    system_prompt: Optional[str] = Field(
        default=None,
        description="Current system prompt for this agent"
    )

    has_token: bool = Field(
        default=False,
        description="Whether a non-empty token is set"
    )

    token_preview: Optional[str] = Field(
        default=None,
        description="First 10 chars of token + '...' (or full token if <= 10 chars)"
    )


class ConfigurationView(BaseModel):
    """Main view model for runtime configuration (subagents only)."""

    subagents: Dict[str, SubAgentConfigView] = Field(
        description="Sub-agent configurations, keyed by agent name"
    )

    available_subagent_types: List[str] = Field(
        description="List of available sub-agent names"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "subagents": {
                    "routing": {
                        "name": "routing",
                        "system_prompt": "Sen Forza navigasyon asistanısın...",
                        "has_token": True,
                        "token_preview": "your-api-t..."
                    }
                },
                "available_subagent_types": ["routing", "chat"]
            }
        }


class ConfigurationUpdateResponse(BaseModel):
    """Response model for configuration update operations."""

    success: bool = Field(description="Whether the update was successful")

    message: str = Field(description="Human-readable message about the update")

    updated_config: ConfigurationView = Field(description="The updated configuration")


__all__ = [
    "SubAgentConfigView",
    "ConfigurationView",
    "ConfigurationUpdateResponse",
]
