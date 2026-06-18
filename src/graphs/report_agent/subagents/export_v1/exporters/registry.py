from typing import Dict, List, Type
from src.graphs.report_agent.subagents.export_v1.exporters.base import BaseExporter


class ExporterRegistry:
    _registry: Dict[str, Type[BaseExporter]] = {}

    @classmethod
    def register(cls, exporter_class: Type[BaseExporter]) -> Type[BaseExporter]:
        cls._registry[exporter_class.FORMAT] = exporter_class
        return exporter_class

    @classmethod
    def get(cls, format: str) -> BaseExporter:
        exporter_cls = cls._registry.get(format)
        if exporter_cls is None:
            raise ValueError(
                f"Unsupported export format: '{format}'. "
                f"Available: {list(cls._registry.keys())}"
            )
        return exporter_cls()

    @classmethod
    def supported_formats(cls) -> List[str]:
        return list(cls._registry.keys())
