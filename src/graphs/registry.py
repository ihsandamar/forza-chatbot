from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Type

@dataclass
class AgentDescriptor:
    name: str
    description: str
    examples: list[str] = field(default_factory=list)
    state_type: str = "messages"
    returns_to_supervisor: bool = True
    cls: Optional[Type] = None

# name → AgentDescriptor
GRAPH_REGISTRY: dict[str, AgentDescriptor] = {}


def register_graph(
    name: str,
    description: str = "",
    examples: list[str] = None,
    state_type: str = "messages",
    returns_to_supervisor: bool = True,
):
    """
    Decorator: bir graph sınıfını GRAPH_REGISTRY'ye kaydeder.

    Kullanım:
        @register_graph(
            name="my_agent",
            description="Kullanıcı X istediğinde devreye girer.",
            examples=["örnek sorgu 1", "örnek sorgu 2"],
        )
        class MyAgentGraph(BaseGraph): ...
    """
    def decorator(cls):
        GRAPH_REGISTRY[name] = AgentDescriptor(
            name=name,
            description=description,
            examples=examples or [],
            state_type=state_type,
            returns_to_supervisor=returns_to_supervisor,
            cls=cls,
        )
        return cls
    return decorator
