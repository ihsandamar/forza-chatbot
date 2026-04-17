from __future__ import annotations

import sys
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.graphs.registry import GRAPH_REGISTRY

if TYPE_CHECKING:
    from src.models.llm import LLM

logger = logging.getLogger(__name__)


class GraphRepository:
    def __init__(self, llm: LLM, app_config=None):
        self.llm = llm
        self.app_config = app_config
        self.register_all()

    def get(self, graph_type: str):
        """Graph instance'ını oluşturur ve build_graph() çağırır."""
        if isinstance(graph_type, dict):
            graph_type = graph_type.get("type") or graph_type.get("name", str(graph_type))
        if graph_type not in GRAPH_REGISTRY:
            raise ValueError(f"Graph tipi bulunamadı: {graph_type}")
        descriptor = GRAPH_REGISTRY[graph_type]
        instance = descriptor.cls.create(llm=self.llm, app_config=self.app_config)
        return instance.build_graph()

    def get_raw(self, graph_type: str):
        """Build etmeden graph instance'ını döner."""
        if isinstance(graph_type, dict):
            graph_type = graph_type.get("type") or graph_type.get("name", str(graph_type))
        if graph_type not in GRAPH_REGISTRY:
            raise ValueError(f"Graph tipi bulunamadı: {graph_type}")
        descriptor = GRAPH_REGISTRY[graph_type]
        return descriptor.cls.create(llm=self.llm, app_config=self.app_config)

    def list_graphs(self):
        return list(GRAPH_REGISTRY.keys())

    def register_all(self):
        if getattr(sys, "frozen", False):
            self._register_explicit()
        else:
            self._register_auto_discover()

    def _register_auto_discover(self):
        """
        src/graphs/*/graph.py pattern'ini glob ile tarar.
        @register_graph decorator tetiklenince GRAPH_REGISTRY dolar.
        """
        import importlib
        from glob import glob

        pattern = str(Path(__file__).parent / "*/graph.py")
        for path in glob(pattern):
            parts = Path(path).parts
            try:
                idx = next(i for i, p in enumerate(parts) if p == "src")
                module_name = ".".join(parts[idx:]).removesuffix(".py")
                importlib.import_module(module_name)
            except StopIteration:
                logger.warning(f"'src' bulunamadı path'te: {path}")
            except ImportError as e:
                logger.warning(f"Graph yüklenemedi: {path} — {e}")

    def _register_explicit(self):
        """
        PyInstaller build için explicit import listesi.
        Yeni agent eklendiğinde sadece buraya 1 satır import eklenir.
        """
        import importlib
        modules = [
            "src.graphs.chat.graph",
            "src.graphs.supervisor.graph",
            "src.graphs.routing.graph",
            "src.graphs.report_agent.graph",
            # YENİ AGENT: "src.graphs.finance_agent.graph"
        ]
        loaded = []
        for mod in modules:
            try:
                importlib.import_module(mod)
                loaded.append(mod.split(".")[-2])  # e.g. "chat"
            except ImportError as e:
                logger.warning(f"Graph yüklenemedi: {mod} — {e}")
        if loaded:
            logger.info(f"Graph'lar yüklendi (explicit mode): {loaded}")
