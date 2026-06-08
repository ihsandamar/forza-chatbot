# src/graphs/report_agent/insight_engine/analyzers/trend.py
import logging
from typing import List

import numpy as np
import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

CHANGE_PCT_THRESHOLD = 5.0  # % — changes below this are ignored
_DATE_COLUMNS = {"DocumentDate"}


class TrendAnalyzer(BaseAnalyzer):
    @property
    def name(self) -> str:
        return "TrendAnalyzer"

    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        if current_df.empty:
            return findings

        # Time series detection: single date dimension, no comparison, >2 rows
        if (
            len(context.dimension_columns) == 1
            and context.dimension_columns[0] in _DATE_COLUMNS
            and comparison_df.empty
            and len(current_df) > 2
        ):
            findings.extend(self._analyze_time_series(current_df, context))
            return findings

        # Segment-based period comparison
        if comparison_df.empty:
            return findings
        findings.extend(self._analyze_segment_change(current_df, comparison_df, context))
        return findings

    def _analyze_segment_change(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        dim_cols = [c for c in context.dimension_columns if c in current_df.columns and c in comparison_df.columns]
        metric_cols = [c for c in context.metric_columns if c in current_df.columns and c in comparison_df.columns]
        if not dim_cols or not metric_cols:
            return findings

        dim = dim_cols[0]
        metric = metric_cols[0]

        merged = current_df[[dim, metric]].merge(
            comparison_df[[dim, metric]].rename(columns={metric: f"{metric}_prev"}),
            on=dim,
            how="inner",
        )
        for _, row in merged.iterrows():
            cur = float(row[metric])
            prev = float(row[f"{metric}_prev"])
            if prev == 0:
                continue
            change_pct = (cur - prev) / prev * 100
            if abs(change_pct) < CHANGE_PCT_THRESHOLD:
                continue
            significance = min(abs(change_pct) / 100, 1.0)
            finding_type = "trend_increase" if change_pct > 0 else "trend_decline"
            findings.append(Finding(
                type=finding_type,
                analyzer=self.name,
                dimension=dim,
                value=str(row[dim]),
                metric=metric,
                current_value=cur,
                comparison_value=prev,
                change_pct=round(change_pct, 2),
                significance=round(significance, 3),
                period_label=context.period_label,
            ))
        return findings

    def _analyze_time_series(
        self,
        df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        metric_cols = [c for c in context.metric_columns if c in df.columns]
        if not metric_cols:
            return findings

        metric = metric_cols[0]
        values = df[metric].astype(float).values
        if len(values) < 3:
            return findings

        x = np.arange(len(values))
        slope, _ = np.polyfit(x, values, 1)
        corr = np.corrcoef(x, values)[0, 1]
        r_squared = float(corr ** 2) if not np.isnan(corr) else 0.0

        value_range = float(values.max() - values.min())
        if value_range == 0:
            return findings
        normalized_slope = abs(slope) / value_range
        if normalized_slope < 0.05:
            return findings

        significance = round(min(normalized_slope * r_squared, 1.0), 3)
        finding_type = "trend_decline" if slope < 0 else "trend_increase"
        first_val = float(values[0])
        last_val = float(values[-1])
        change_pct = round((last_val - first_val) / first_val * 100, 2) if first_val != 0 else 0.0
        findings.append(Finding(
            type=finding_type,
            analyzer=self.name,
            dimension=context.dimension_columns[0],
            value="zaman serisi",
            metric=metric,
            current_value=last_val,
            comparison_value=first_val,
            change_pct=change_pct,
            significance=significance,
            period_label=context.period_label,
            extra={"slope": round(float(slope), 4), "r_squared": round(r_squared, 4)},
        ))
        return findings
