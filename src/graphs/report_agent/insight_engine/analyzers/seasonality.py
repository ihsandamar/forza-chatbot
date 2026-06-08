# src/graphs/report_agent/insight_engine/analyzers/seasonality.py
import logging
from typing import List

import numpy as np
import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

MIN_ROWS = 14
AUTOCORR_THRESHOLD = 0.45
DATE_COLUMNS = {"DocumentDate"}


class SeasonalityAnalyzer(BaseAnalyzer):
    @property
    def name(self) -> str:
        return "SeasonalityAnalyzer"

    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        date_cols = [c for c in context.dimension_columns if c in DATE_COLUMNS and c in current_df.columns]
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
        lag = 7
        if len(values) <= lag:
            return findings

        v1 = values[:-lag]
        v2 = values[lag:]
        corr_matrix = np.corrcoef(v1, v2)
        autocorr = float(corr_matrix[0, 1]) if not np.isnan(corr_matrix[0, 1]) else 0.0

        if abs(autocorr) < AUTOCORR_THRESHOLD:
            return findings

        significance = round(min(abs(autocorr), 1.0), 3)

        df["dow"] = df[date_col].dt.dayofweek
        dow_avg = df.groupby("dow")[metric].mean()
        peak_dow = int(dow_avg.idxmax())
        trough_dow = int(dow_avg.idxmin())
        dow_names = {0: "Pazartesi", 1: "Salı", 2: "Çarşamba", 3: "Perşembe",
                     4: "Cuma", 5: "Cumartesi", 6: "Pazar"}

        findings.append(Finding(
            type="seasonal_peak",
            analyzer=self.name,
            dimension="DayOfWeek",
            value=dow_names.get(peak_dow, str(peak_dow)),
            metric=metric,
            current_value=float(dow_avg.max()),
            comparison_value=float(dow_avg.mean()),
            change_pct=round((dow_avg.max() - dow_avg.mean()) / dow_avg.mean() * 100, 2),
            significance=significance,
            period_label=context.period_label,
            extra={"autocorr_lag7": round(autocorr, 3)},
        ))

        if float(dow_avg.min()) < float(dow_avg.mean()) * 0.7:
            findings.append(Finding(
                type="seasonal_trough",
                analyzer=self.name,
                dimension="DayOfWeek",
                value=dow_names.get(trough_dow, str(trough_dow)),
                metric=metric,
                current_value=float(dow_avg.min()),
                comparison_value=float(dow_avg.mean()),
                change_pct=round((dow_avg.min() - dow_avg.mean()) / dow_avg.mean() * 100, 2),
                significance=round(significance * 0.8, 3),
                period_label=context.period_label,
                extra={"autocorr_lag7": round(autocorr, 3)},
            ))

        return findings
