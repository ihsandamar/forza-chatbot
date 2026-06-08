# src/graphs/report_agent/insight_engine/analyzers/segment.py
import logging
from typing import List

import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

PARETO_THRESHOLD = 0.80
VS_AVG_THRESHOLD = 30.0  # %


class SegmentComparator(BaseAnalyzer):
    @property
    def name(self) -> str:
        return "SegmentComparator"

    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        if current_df.empty or len(current_df) < 2:
            return findings

        dim_cols = [c for c in context.dimension_columns if c in current_df.columns]
        metric_cols = [c for c in context.metric_columns if c in current_df.columns]
        if not dim_cols or not metric_cols:
            return findings

        dim = dim_cols[0]
        metric = metric_cols[0]
        df = current_df[[dim, metric]].copy()
        df[metric] = df[metric].astype(float)
        df = df.sort_values(metric, ascending=False).reset_index(drop=True)

        mean = float(df[metric].mean())
        total = float(df[metric].sum())
        if mean == 0 or total == 0:
            return findings

        # Top performer
        top_row = df.iloc[0]
        top_val = float(top_row[metric])
        top_vs_avg = (top_val - mean) / mean * 100
        if top_vs_avg >= VS_AVG_THRESHOLD:
            findings.append(Finding(
                type="top_performer",
                analyzer=self.name,
                dimension=dim,
                value=str(top_row[dim]),
                metric=metric,
                current_value=top_val,
                comparison_value=mean,
                change_pct=round(top_vs_avg, 2),
                significance=round(min(top_vs_avg / 200, 1.0), 3),
                period_label=context.period_label,
                extra={"rank": 1, "total_segments": len(df)},
            ))

        # Bottom performer
        bottom_row = df.iloc[-1]
        bottom_val = float(bottom_row[metric])
        bottom_vs_avg = (bottom_val - mean) / mean * 100
        if bottom_vs_avg <= -VS_AVG_THRESHOLD:
            findings.append(Finding(
                type="bottom_performer",
                analyzer=self.name,
                dimension=dim,
                value=str(bottom_row[dim]),
                metric=metric,
                current_value=bottom_val,
                comparison_value=mean,
                change_pct=round(bottom_vs_avg, 2),
                significance=round(min(abs(bottom_vs_avg) / 200, 1.0), 3),
                period_label=context.period_label,
                extra={"rank": len(df), "total_segments": len(df)},
            ))

        # Pareto: top-20% segment contribution
        top_n = max(1, len(df) // 5)
        top_share = float(df.iloc[:top_n][metric].sum()) / total
        if top_share >= PARETO_THRESHOLD:
            top_names = ", ".join(str(v) for v in df.iloc[:top_n][dim].tolist())
            findings.append(Finding(
                type="pareto_dominant",
                analyzer=self.name,
                dimension=dim,
                value=top_names,
                metric=metric,
                current_value=float(df.iloc[:top_n][metric].sum()),
                comparison_value=total,
                change_pct=round(top_share * 100, 2),
                significance=round(min((top_share - 0.5) * 2, 1.0), 3),
                period_label=context.period_label,
                extra={"top_n": top_n, "share_pct": round(top_share * 100, 2)},
            ))

        return findings
