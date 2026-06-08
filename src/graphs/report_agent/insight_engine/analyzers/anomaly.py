# src/graphs/report_agent/insight_engine/analyzers/anomaly.py
import logging
from typing import List

import numpy as np
import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

Z_SCORE_THRESHOLD = 1.5


class AnomalyDetector(BaseAnalyzer):
    @property
    def name(self) -> str:
        return "AnomalyDetector"

    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        if current_df.empty or len(current_df) < 3:
            return findings

        dim_cols = [c for c in context.dimension_columns if c in current_df.columns]
        metric_cols = [c for c in context.metric_columns if c in current_df.columns]
        if not dim_cols or not metric_cols:
            return findings

        dim = dim_cols[0]
        metric = metric_cols[0]
        values = current_df[metric].astype(float)
        mean = float(values.mean())
        std = float(values.std())
        if std == 0:
            return findings

        for _, row in current_df.iterrows():
            val = float(row[metric])
            z = (val - mean) / std
            if abs(z) < Z_SCORE_THRESHOLD:
                continue
            finding_type = "anomaly_high" if z > 0 else "anomaly_low"
            significance = round(min(abs(z) / 4, 1.0), 3)
            vs_avg_pct = round((val - mean) / mean * 100, 2) if mean != 0 else 0.0
            findings.append(Finding(
                type=finding_type,
                analyzer=self.name,
                dimension=dim,
                value=str(row[dim]),
                metric=metric,
                current_value=val,
                comparison_value=mean,
                change_pct=vs_avg_pct,
                significance=significance,
                period_label=context.period_label,
                extra={"z_score": round(z, 3), "mean": round(mean, 2), "std": round(std, 2)},
            ))
        return findings
