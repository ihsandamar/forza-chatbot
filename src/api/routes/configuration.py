"""
Configuration Routes.

REST API endpoints for runtime configuration management.

Architecture:
    - GET /api/configuration: Retrieve current configuration
    - POST /api/configuration: Update configuration

Principles:
    - KISS: Simple, focused endpoints
    - SRP: Each endpoint has one responsibility
    - DIP: Depends on ChatService abstraction
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any

from src.api.services.chat_service import ChatService
from src.api.dependencies import get_chat_service
from src.api.models.requests.configuration import (
    ConfigurationUpdateRequest,
    LLMConfigUpdateRequest,
    SubAgentConfigUpdateRequest
)
from src.api.models.responses.configuration import (
    ConfigurationView,
    ConfigurationUpdateResponse,
    LLMConfigView,
    SubAgentConfigView
)
from src.core.runtime_config import RuntimeConfiguration

router = APIRouter()


def _build_configuration_view(runtime_config: RuntimeConfiguration) -> ConfigurationView:
    """
    Build ConfigurationView from RuntimeConfiguration.

    KISS: Simple transformation logic using JSON Schema.
    SRP: Single responsibility - view construction.

    Args:
        runtime_config: RuntimeConfiguration instance

    Returns:
        ConfigurationView for API response with JSON Schema
    """
    # Build LLM config view with manual schema (LLMRuntimeConfig is a dataclass, not Pydantic)
    llm_schema = {
        "type": "object",
        "title": "LLMRuntimeConfig",
        "properties": {
            "model": {
                "type": "string",
                "default": "gpt-4o-mini",
                "title": "Model",
                "description": "LLM model name (e.g., 'gpt-4o-mini', 'claude-sonnet-4-5')"
            },
            "temperature": {
                "type": "number",
                "default": 0.0,
                "minimum": 0.0,
                "maximum": 1.0,
                "title": "Temperature",
                "description": "Model temperature for response generation (0.0 = deterministic, 1.0 = creative)"
            },
            "api_key": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "API Key",
                "description": "API key for the LLM provider (sensitive, will be masked)"
            },
            "provider": {
                "type": "string",
                "default": "openai",
                "title": "Provider",
                "description": "LLM provider name (e.g., 'openai', 'anthropic')"
            },
            "base_url": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Base URL",
                "description": "Custom base URL for API calls (optional)"
            }
        }
    }

    llm_values = {
        "model": runtime_config.llm.model,
        "temperature": runtime_config.llm.temperature,
        "provider": runtime_config.llm.provider,
        "base_url": runtime_config.llm.base_url,
        "has_api_key": runtime_config.llm.api_key is not None and runtime_config.llm.api_key != ""
    }

    llm_view = LLMConfigView(
        schema=llm_schema,
        values=llm_values
    )

    # Build sub-agent config views with schemas
    subagent_views: Dict[str, SubAgentConfigView] = {}
    for name, config in runtime_config.subagents.items():
        # Get JSON Schema from Pydantic model
        agent_schema = config.model_json_schema()

        # Get current values (with masking for sensitive fields)
        config_dict = config.model_dump()

        # Mask token
        token = config_dict.get('token', '')
        has_token = token is not None and token != ""
        token_preview = None
        if has_token and token:
            token_preview = token[:10] + "..." if len(token) > 10 else token

        # Build values dict with masked sensitive data
        values = {
            **config_dict,
            "has_token": has_token,
            "token_preview": token_preview
        }
        # Remove actual token from values for security
        values.pop('token', None)

        subagent_views[name] = SubAgentConfigView(
            name=name,
            agent_type=config.__class__.__name__,
            schema=agent_schema,
            values=values
        )

    return ConfigurationView(
        graph_type=runtime_config.graph_type,
        llm=llm_view,
        subagents=subagent_views,
        available_subagent_types=list(runtime_config.subagents.keys())
    )


@router.get(
    "",
    response_model=ConfigurationView,
    summary="Get current configuration",
    description="Retrieve the current runtime configuration including LLM settings and sub-agent configurations"
)
async def get_configuration(
    chat_service: ChatService = Depends(get_chat_service)
) -> ConfigurationView:
    """
    Get current runtime configuration.

    Returns:
        ConfigurationView with current settings

    Raises:
        HTTPException: If runtime config is not available
    """
    try:
        # Get runtime config from chatbot
        if not chat_service.chatbot:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chatbot not initialized"
            )

        runtime_config = chat_service.chatbot.runtime_config
        if not runtime_config:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Runtime configuration not available"
            )

        return _build_configuration_view(runtime_config)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve configuration: {str(e)}"
        )


@router.post(
    "",
    response_model=ConfigurationUpdateResponse,
    summary="Update configuration",
    description="Update runtime configuration including LLM settings and sub-agent configurations"
)
async def update_configuration(
    update_request: ConfigurationUpdateRequest,
    chat_service: ChatService = Depends(get_chat_service)
) -> ConfigurationUpdateResponse:
    """
    Update runtime configuration.

    Args:
        update_request: Configuration updates to apply

    Returns:
        ConfigurationUpdateResponse with updated config

    Raises:
        HTTPException: If update fails or chatbot not available
    """
    try:
        # Validate chatbot availability
        if not chat_service.chatbot:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chatbot not initialized"
            )

        runtime_config = chat_service.chatbot.runtime_config
        if not runtime_config:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Runtime configuration not available"
            )

        # Track what was updated
        updated_items = []

        # Update LLM configuration if provided
        if update_request.llm:
            llm_updates = {}
            if update_request.llm.model is not None:
                llm_updates['model'] = update_request.llm.model
                updated_items.append("LLM model")
            if update_request.llm.temperature is not None:
                llm_updates['temperature'] = update_request.llm.temperature
                updated_items.append("LLM temperature")
            if update_request.llm.api_key is not None:
                llm_updates['api_key'] = update_request.llm.api_key
                updated_items.append("LLM API key")
            if update_request.llm.provider is not None:
                llm_updates['provider'] = update_request.llm.provider
                updated_items.append("LLM provider")
            if update_request.llm.base_url is not None:
                llm_updates['base_url'] = update_request.llm.base_url
                updated_items.append("LLM base URL")

            if llm_updates:
                runtime_config = runtime_config.update_llm(**llm_updates)

        # Update sub-agent configurations if provided
        if update_request.subagents:
            for agent_name, agent_update in update_request.subagents.items():
                # Check if agent exists
                if runtime_config.get_subagent(agent_name) is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Sub-agent '{agent_name}' not found"
                    )

                # Build update dict
                agent_updates = {}
                if agent_update.system_prompt is not None:
                    agent_updates['system_prompt'] = agent_update.system_prompt
                    updated_items.append(f"{agent_name} system prompt")
                if agent_update.token is not None:
                    agent_updates['token'] = agent_update.token
                    updated_items.append(f"{agent_name} token")

                # Add extra params if provided
                if agent_update.extra_params:
                    agent_updates.update(agent_update.extra_params)
                    updated_items.append(f"{agent_name} extra params")

                if agent_updates:
                    runtime_config = runtime_config.update_subagent(agent_name, **agent_updates)

        # Apply updated configuration to chatbot
        chat_service.chatbot.update_runtime_config(runtime_config)

        # Build success message
        if updated_items:
            message = f"Configuration updated successfully: {', '.join(updated_items)}"
        else:
            message = "No changes were made (all values were None)"

        return ConfigurationUpdateResponse(
            success=True,
            message=message,
            updated_config=_build_configuration_view(runtime_config)
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update configuration: {str(e)}"
        )


__all__ = ["router"]
