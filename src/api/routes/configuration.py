"""
Configuration Routes — sub-agent runtime settings only.

GET  /api/configuration  → current subagent settings
POST /api/configuration  → update system_prompt / token per agent
"""
import logging
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.services.chat_service import ChatService
from src.api.dependencies import get_chat_service
from src.api.models.requests.configuration import (
    ConfigurationUpdateRequest,
)
from src.api.models.responses.configuration import (
    ConfigurationView,
    ConfigurationUpdateResponse,
    SubAgentConfigView,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_view(settings) -> ConfigurationView:
    """Build ConfigurationView from RuntimeAgentSettings."""
    subagent_views: Dict[str, SubAgentConfigView] = {}
    if settings:
        for name, s in settings.subagents.items():
            token_preview = None
            if s.token:
                token_preview = s.token[:10] + "..." if len(s.token) > 10 else s.token
            subagent_views[name] = SubAgentConfigView(
                name=name,
                system_prompt=s.system_prompt,
                has_token=bool(s.token),
                token_preview=token_preview,
            )
    return ConfigurationView(
        subagents=subagent_views,
        available_subagent_types=list(subagent_views.keys()),
    )


@router.get(
    "",
    response_model=ConfigurationView,
    summary="Get current sub-agent settings",
)
async def get_configuration(
    chat_service: ChatService = Depends(get_chat_service),
) -> ConfigurationView:
    if not chat_service.chatbot:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chatbot not initialized",
        )
    settings = chat_service.chatbot.get_runtime_settings()
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime settings not available",
        )
    return _build_view(settings)


@router.post(
    "",
    response_model=ConfigurationUpdateResponse,
    summary="Update sub-agent settings",
)
async def update_configuration(
    update_request: ConfigurationUpdateRequest,
    chat_service: ChatService = Depends(get_chat_service),
) -> ConfigurationUpdateResponse:
    if not chat_service.chatbot:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chatbot not initialized",
        )
    settings = chat_service.chatbot.get_runtime_settings()
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime settings not available",
        )

    updated_items = []
    if update_request.subagents:
        for agent_name, agent_update in update_request.subagents.items():
            agent_updates: dict = {}
            if agent_update.system_prompt is not None:
                agent_updates["system_prompt"] = agent_update.system_prompt
                updated_items.append(f"{agent_name} system_prompt")
            if agent_update.token is not None:
                agent_updates["token"] = agent_update.token
                updated_items.append(f"{agent_name} token")
            if agent_updates:
                settings = settings.update_subagent(agent_name, **agent_updates)

    chat_service.chatbot.update_runtime_settings(settings)
    message = f"Updated: {', '.join(updated_items)}" if updated_items else "No changes"
    return ConfigurationUpdateResponse(
        success=True,
        message=message,
        updated_config=_build_view(settings),
    )


__all__ = ["router"]
