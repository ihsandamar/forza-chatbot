# src/graphs/report_agent/insight_engine/analyzers/base.py
from abc import ABC, abstractmethod
from typing import List

import pandas as pd

from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding


class BaseAnalyzer(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        ...
