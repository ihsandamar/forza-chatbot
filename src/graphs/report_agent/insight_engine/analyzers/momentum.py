import logging
from typing import List

import numpy as np
import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

MIN_ROWS = 14
WOW_THRESHOLD = 20.0
VOLATILITY_THRESHOLD = 0.5
MOMENTUM_THRESHOLD = 0.07
_DATE_COLUMNS = {"DocumentDate"}


class MomentumAnalyzer(BaseAnalyzer):
    @property
    def name(self) -> str:
        return "MomentumAnalyzer"

    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        date_cols = [c for c in context.dimension_columns if c in _DATE_COLUMNS and c in current_df.columns]
        metric_cols = [c for c in context.metric_columns if c in current_df.columns]
        if not date_cols or not metric_cols:
            return findings

        date_col = date_cols[0]
        metric = metric_cols[0]
        df = current_df[[date_col, metric]].copy()
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        df = df.groupby(date_col)[metric].sum().reset_index().sort_values(date_col)

        if len(df) < MIN_ROWS:
            return findings

        values = df[metric].astype(float).values

        # WoW: last 7 vs previous 7
        last7 = values[-7:]
        prev7 = values[-14:-7]
        prev7_sum = float(prev7.sum())
        if abs(prev7_sum) > 1e-9:
            wow_pct = (float(last7.sum()) - prev7_sum) / prev7_sum * 100
            if wow_pct >= WOW_THRESHOLD:
                findings.append(Finding(
                    type="wow_surge",
                    analyzer=self.name,
                    dimension=date_col,
                    value="son 7 gün",
                    metric=metric,
                    current_value=round(float(last7.sum()), 2),
                    comparison_value=round(prev7_sum, 2),
                    change_pct=round(wow_pct, 2),
                    significance=round(min(wow_pct / 100, 1.0), 3),
                    period_label=context.period_label,
                    extra={"last7_sum": round(float(last7.sum()), 2), "prev7_sum": round(prev7_sum, 2)},
                ))
            elif wow_pct <= -WOW_THRESHOLD:
                findings.append(Finding(
                    type="wow_drop",
                    analyzer=self.name,
                    dimension=date_col,
                    value="son 7 gün",
                    metric=metric,
                    current_value=round(float(last7.sum()), 2),
                    comparison_value=round(prev7_sum, 2),
                    change_pct=round(wow_pct, 2),
                    significance=round(min(abs(wow_pct) / 100, 1.0), 3),
                    period_label=context.period_label,
                    extra={"last7_sum": round(float(last7.sum()), 2), "prev7_sum": round(prev7_sum, 2)},
                ))

        # Volatility: coefficient of variation
        mean_val = float(np.mean(values))
        std_val = float(np.std(values))
        if mean_val > 0:
            cv = std_val / mean_val
            if cv >= VOLATILITY_THRESHOLD:
                findings.append(Finding(
                    type="high_volatility",
                    analyzer=self.name,
                    dimension=date_col,
                    value="dönem geneli",
                    metric=metric,
                    current_value=round(std_val, 2),
                    comparison_value=round(mean_val, 2),
                    change_pct=round(cv * 100, 2),
                    significance=round(min(cv / 2, 1.0), 3),
                    period_label=context.period_label,
                    extra={"cv": round(cv, 4), "mean": round(mean_val, 2), "std": round(std_val, 2)},
                ))

        # Momentum score: slope × r²
        x = np.arange(len(values), dtype=float)
        slope, _ = np.polyfit(x, values, 1)
        corr = np.corrcoef(x, values)[0, 1]
        r_squared = float(corr ** 2) if not np.isnan(corr) else 0.0
        value_range = float(values.max() - values.min())
        if value_range > 0:
            normalized_slope = slope / value_range
            momentum_score = normalized_slope * r_squared
            if momentum_score >= MOMENTUM_THRESHOLD:
                first_val = float(values[0])
                last_val = float(values[-1])
                chg = (last_val - first_val) / first_val * 100 if first_val != 0 else 0.0
                findings.append(Finding(
                    type="high_momentum",
                    analyzer=self.name,
                    dimension=date_col,
                    value="dönem geneli",
                    metric=metric,
                    current_value=round(last_val, 2),
                    comparison_value=round(first_val, 2),
                    change_pct=round(chg, 2),
                    significance=round(min(abs(momentum_score), 1.0), 3),
                    period_label=context.period_label,
                    extra={
                        "momentum_score": round(float(momentum_score), 4),
                        "slope": round(float(slope), 4),
                        "r_squared": round(r_squared, 4),
                    },
                ))

        # Acceleration: first-half vs second-half slope
        if len(values) >= 10:
            mid = len(values) // 2
            x1 = np.arange(mid, dtype=float)
            x2 = np.arange(len(values) - mid, dtype=float)
            slope1, _ = np.polyfit(x1, values[:mid], 1)
            slope2, _ = np.polyfit(x2, values[mid:], 1)
            if value_range > 0 and slope1 != 0:
                norm_s1 = slope1 / value_range
                norm_s2 = slope2 / value_range
                ratio = norm_s2 / norm_s1
                extra_acc = {"first_half_slope": round(float(norm_s1), 4), "second_half_slope": round(float(norm_s2), 4)}
                if norm_s1 > 0 and ratio >= 1.5:
                    findings.append(Finding(
                        type="accelerating",
                        analyzer=self.name,
                        dimension=date_col,
                        value="ikinci yarı",
                        metric=metric,
                        current_value=round(float(norm_s2), 4),
                        comparison_value=round(float(norm_s1), 4),
                        change_pct=round((ratio - 1) * 100, 2),
                        significance=round(min((ratio - 1) / 2, 1.0), 3),
                        period_label=context.period_label,
                        extra=extra_acc,
                    ))
                elif norm_s1 > 0 and norm_s2 <= norm_s1 * 0.4:
                    findings.append(Finding(
                        type="decelerating",
                        analyzer=self.name,
                        dimension=date_col,
                        value="ikinci yarı",
                        metric=metric,
                        current_value=round(float(norm_s2), 4),
                        comparison_value=round(float(norm_s1), 4),
                        change_pct=round((ratio - 1) * 100, 2),
                        significance=round(min(abs(1 - ratio) / 2, 1.0), 3),
                        period_label=context.period_label,
                        extra=extra_acc,
                    ))

        return findings
