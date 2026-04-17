"""
Configuration Request Models.
"""
from typing import Optional, Dict
from pydantic import BaseModel, Field


class SubAgentConfigUpdateRequest(BaseModel):
    """Request model for updating one sub-agent's runtime settings."""

    system_prompt: Optional[str] = Field(
        default=None,
        description="New system prompt for the sub-agent",
        example="Sen Forza navigasyon asistanısın.",
    )

    token: Optional[str] = Field(
        default=None,
        description="Authentication token for the sub-agent",
        example="secret-token-123",
    )


class ConfigurationUpdateRequest(BaseModel):
    """Request model for updating sub-agent runtime settings."""

    subagents: Optional[Dict[str, SubAgentConfigUpdateRequest]] = Field(
        default=None,
        description="Sub-agent updates, keyed by agent name",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "subagents": {
                    "routing": {"token": "your-api-token"},
                    "chat": {"system_prompt": "Sen yardımcı bir asistansın."},
                }
            }
        }


__all__ = ["SubAgentConfigUpdateRequest", "ConfigurationUpdateRequest"]
