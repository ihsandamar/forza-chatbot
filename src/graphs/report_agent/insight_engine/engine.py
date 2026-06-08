import logging
from typing import List

import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)


class MathEngine:
    def __init__(self, analyzers: List[BaseAnalyzer]):
        self.analyzers = analyzers

    def run(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        all_findings: List[Finding] = []
        for analyzer in self.analyzers:
            try:
                findings = analyzer.analyze(current_df, comparison_df, context)
                all_findings.extend(findings)
                logger.debug(f"[MATH_ENGINE] {analyzer.name}: {len(findings)} findings")
            except Exception as exc:
                logger.warning(f"[MATH_ENGINE] {analyzer.name} failed: {exc}")
        return all_findings


def build_default_engine() -> MathEngine:
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    from src.graphs.report_agent.insight_engine.analyzers.multidim import MultiDimAnalyzer
    from src.graphs.report_agent.insight_engine.analyzers.seasonality import SeasonalityAnalyzer
    from src.graphs.report_agent.insight_engine.analyzers.momentum import MomentumAnalyzer
    from src.graphs.report_agent.insight_engine.analyzers.correlation import CorrelationAnalyzer

    return MathEngine(analyzers=[
        TrendAnalyzer(),
        AnomalyDetector(),
        SegmentComparator(),
        MultiDimAnalyzer(),
        SeasonalityAnalyzer(),
        MomentumAnalyzer(),
        CorrelationAnalyzer(),
    ])
