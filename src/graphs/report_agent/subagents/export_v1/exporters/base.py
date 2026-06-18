from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any, Dict, List, Optional


class BaseExporter(ABC):
    FORMAT: str

    @abstractmethod
    def export(
        self,
        results: List[Dict[str, Any]],
        spec: "ExportSpec",  # noqa: F821 — forward ref
        chart_figure=None,
        insight_text: str = "",
    ) -> BytesIO: ...

    @property
    @abstractmethod
    def content_type(self) -> str: ...
