# src/graphs/report_agent/insight_engine/analyzers/multidim.py
import logging
from typing import List

import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

TIME_DIM_COLUMNS = {"DayOfWeek", "Hour"}
VS_AVG_THRESHOLD = 40.0  # %


class MultiDimAnalyzer(BaseAnalyzer):
    @property
    def name(self) -> str:
        return "MultiDimAnalyzer"

    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        if current_df.empty:
            return findings

        time_cols = [c for c in context.dimension_columns if c in TIME_DIM_COLUMNS and c in current_df.columns]
        metric_cols = [c for c in context.metric_columns if c in current_df.columns]
        if not time_cols or not metric_cols:
            return findings

        dim = time_cols[0]
        metric = metric_cols[0]
        df = current_df[[dim, metric]].copy()
        df[metric] = df[metric].astype(float)
        mean = float(df[metric].mean())
        if mean == 0:
            return findings

        peak_row = df.loc[df[metric].idxmax()]
        peak_val = float(peak_row[metric])
        peak_vs_avg = (peak_val - mean) / mean * 100
        if peak_vs_avg >= VS_AVG_THRESHOLD:
            dim_val = peak_row[dim]
            dim_str = str(int(dim_val)) if isinstance(dim_val, float) and dim_val == int(dim_val) else str(dim_val)
            findings.append(Finding(
                type="peak_period",
                analyzer=self.name,
                dimension=dim,
                value=dim_str,
                metric=metric,
                current_value=peak_val,
                comparison_value=mean,
                change_pct=round(peak_vs_avg, 2),
                significance=round(min(peak_vs_avg / 200, 1.0), 3),
                period_label=context.period_label,
            ))

        weak_row = df.loc[df[metric].idxmin()]
        weak_val = float(weak_row[metric])
        weak_vs_avg = (weak_val - mean) / mean * 100
        if weak_vs_avg <= -VS_AVG_THRESHOLD:
            dim_val = weak_row[dim]
            dim_str = str(int(dim_val)) if isinstance(dim_val, float) and dim_val == int(dim_val) else str(dim_val)
            findings.append(Finding(
                type="weak_period",
                analyzer=self.name,
                dimension=dim,
                value=dim_str,
                metric=metric,
                current_value=weak_val,
                comparison_value=mean,
                change_pct=round(weak_vs_avg, 2),
                significance=round(min(abs(weak_vs_avg) / 200, 1.0), 3),
                period_label=context.period_label,
            ))

        return findings
