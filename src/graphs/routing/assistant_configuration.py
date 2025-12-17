
from pydantic import BaseModel, Field

from src.models.base_assistant_configuration import BaseAssistantConfiguration


class RoutingAssistantConfiguration(BaseAssistantConfiguration):
    token: str = Field(
        default="",
        description="Forza API token"
    )