# src/graphs/report_agent/insight_engine/analyzers/anomaly.py
import logging
from typing import List

import numpy as np
import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

Z_SCORE_THRESHOLD = 1.5

_DATE_COLUMNS = {"DocumentDate"}
_MIN_TS_ROWS = 10
_CUSUM_H = 4.0
_CUSUM_K = 0.5


def _cusum_detect(values: np.ndarray) -> int:
    """Return index of first CUSUM breach, or -1 if none."""
    mean = float(np.mean(values))
    std = float(np.std(values))
    if std == 0:
        return -1
    z = (values - mean) / std
    cusum_pos = 0.0
    cusum_neg = 0.0
    for i in range(1, len(z)):
        cusum_pos = max(0.0, cusum_pos + float(z[i]) - _CUSUM_K)
        cusum_neg = min(0.0, cusum_neg + float(z[i]) + _CUSUM_K)
        if cusum_pos > _CUSUM_H or cusum_neg < -_CUSUM_H:
            return i
    return -1


def _changepoint_detect(values: np.ndarray, min_size: int = 4) -> int:
    """Variance-based binary segmentation. Returns best split index or -1."""
    n = len(values)
    if n < 2 * min_size:
        return -1
    baseline_cost = float(np.var(values)) * n
    if baseline_cost == 0:
        return -1
    best_idx = -1
    best_cost = baseline_cost
    for i in range(min_size, n - min_size + 1):
        cost = float(np.var(values[:i])) * i + float(np.var(values[i:])) * (n - i)
        if cost < best_cost:
            best_cost = cost
            best_idx = i
    if best_idx == -1:
        return -1
    reduction = (baseline_cost - best_cost) / baseline_cost
    return best_idx if reduction >= 0.30 else -1


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

        # Time-series shift detection (CUSUM + Changepoint)
        date_cols_ts = [c for c in context.dimension_columns if c in _DATE_COLUMNS and c in current_df.columns]
        metric_ts = [c for c in context.metric_columns if c in current_df.columns]
        if date_cols_ts and metric_ts:
            findings.extend(self._analyze_time_shifts(current_df, date_cols_ts[0], metric_ts[0], context))

        return findings

    def _analyze_time_shifts(
        self,
        df: pd.DataFrame,
        date_col: str,
        metric: str,
        context: AnalysisContext,
    ) -> List[Finding]:
        ts = df[[date_col, metric]].copy()
        ts[date_col] = pd.to_datetime(ts[date_col], errors="coerce")
        ts = ts.dropna(subset=[date_col])
        ts = ts.groupby(date_col)[metric].sum().reset_index().sort_values(date_col)
        if len(ts) < _MIN_TS_ROWS:
            return []

        values = ts[metric].astype(float).values
        dates = ts[date_col].values
        shift_findings: List[Finding] = []

        # CUSUM
        shift_idx = _cusum_detect(values)
        cusum_date: str = ""
        if shift_idx != -1:
            before_avg = float(np.mean(values[:shift_idx]))
            after_avg = float(np.mean(values[shift_idx:]))
            cusum_date = str(pd.Timestamp(dates[shift_idx]).date())
            direction = "up" if after_avg > before_avg else "down"
            pct = (after_avg - before_avg) / before_avg * 100 if before_avg != 0 else 0.0
            sig = round(min(abs(pct) / 100, 1.0), 3)
            if sig >= 0.15:
                shift_findings.append(Finding(
                    type="cusum_shift",
                    analyzer=self.name,
                    dimension=date_col,
                    value=cusum_date,
                    metric=metric,
                    current_value=round(after_avg, 2),
                    comparison_value=round(before_avg, 2),
                    change_pct=round(pct, 2),
                    significance=sig,
                    period_label=context.period_label,
                    extra={"shift_date": cusum_date, "direction": direction,
                           "before_avg": round(before_avg, 2), "after_avg": round(after_avg, 2)},
                ))

        # Changepoint
        cp_idx = _changepoint_detect(values)
        if cp_idx != -1:
            before_avg = float(np.mean(values[:cp_idx]))
            after_avg = float(np.mean(values[cp_idx:]))
            cp_date = str(pd.Timestamp(dates[cp_idx]).date())
            pct = (after_avg - before_avg) / before_avg * 100 if before_avg != 0 else 0.0
            sig = round(min(abs(pct) / 100, 1.0), 3)
            if sig >= 0.15 and cp_date != cusum_date:
                shift_findings.append(Finding(
                    type="regime_change",
                    analyzer=self.name,
                    dimension=date_col,
                    value=cp_date,
                    metric=metric,
                    current_value=round(after_avg, 2),
                    comparison_value=round(before_avg, 2),
                    change_pct=round(pct, 2),
                    significance=sig,
                    period_label=context.period_label,
                    extra={"changepoint_date": cp_date,
                           "before_avg": round(before_avg, 2), "after_avg": round(after_avg, 2)},
                ))

        return shift_findings
