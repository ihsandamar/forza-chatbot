# src/graphs/report_agent/insight_engine/analyzers/seasonality.py
import logging
from typing import List

import numpy as np
import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

MIN_ROWS = 7
AUTOCORR_THRESHOLD = 0.45
DATE_COLUMNS = {"DocumentDate"}


def _fft_dominant_period(values: np.ndarray) -> int:
    """FFT ile dominant periyot bul. Detrend edilmiş sinyale uygulanır.
    Returns period (>=2) or 0 if not significant."""
    n = len(values)
    if n < 8:
        return 0
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, values, 1)
    detrended = values - (slope * x + intercept)
    fft_vals = np.abs(np.fft.rfft(detrended))
    freqs = np.fft.rfftfreq(n)
    fft_vals[0] = 0.0  # DC bileşeni yoksay
    if len(fft_vals) < 2:
        return 0
    peak_idx = int(np.argmax(fft_vals))
    if peak_idx == 0 or freqs[peak_idx] == 0:
        return 0
    period = round(1.0 / float(freqs[peak_idx]))
    # Sadece güçlü pike anlam ver: peak > 3× diğerlerin ortalaması
    others = np.delete(fft_vals, peak_idx)
    if len(others) == 0 or float(fft_vals[peak_idx]) < 3.0 * float(np.mean(others)):
        return 0
    return max(2, int(period))


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

        # FFT period detection — runs before autocorr early-return
        dominant_period = _fft_dominant_period(values)
        if dominant_period > 0 and dominant_period != 7:
            sig = round(min(max(abs(autocorr), 0.3), 1.0), 3)
            findings.append(Finding(
                type="periodic_pattern",
                analyzer=self.name,
                dimension=date_col,
                value=f"{dominant_period} günlük döngü",
                metric=metric,
                current_value=float(dominant_period),
                comparison_value=7.0,
                change_pct=0.0,
                significance=sig,
                period_label=context.period_label,
                extra={"fft_period": dominant_period, "autocorr_lag7": round(autocorr, 3)},
            ))

        if abs(autocorr) < AUTOCORR_THRESHOLD:
            return findings  # returns here with any FFT findings

        significance = round(min(abs(autocorr), 1.0), 3)

        df["dow"] = df[date_col].dt.dayofweek
        dow_avg = df.groupby("dow")[metric].mean()
        peak_dow = int(dow_avg.idxmax())
        trough_dow = int(dow_avg.idxmin())
        dow_names = {0: "Pazartesi", 1: "Salı", 2: "Çarşamba", 3: "Perşembe",
                     4: "Cuma", 5: "Cumartesi", 6: "Pazar"}
        dow_avg_filled = dow_avg.reindex(range(7), fill_value=0.0)
        dow_averages = {
            dow_names.get(i, str(i)): round(float(dow_avg_filled.iloc[i]), 2)
            for i in range(7)
        }
        min_dow_val = float(dow_avg.min())
        peak_vs_trough_ratio = round(float(dow_avg.max()) / min_dow_val, 2) if min_dow_val > 0 else 0.0

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
            extra={
                "autocorr_lag7": round(autocorr, 3),
                "fft_period": dominant_period,
                "dow_averages": dow_averages,
                "peak_vs_trough_ratio": peak_vs_trough_ratio,
            },
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
                extra={
                    "autocorr_lag7": round(autocorr, 3),
                    "fft_period": dominant_period,
                    "dow_averages": dow_averages,
                    "peak_vs_trough_ratio": peak_vs_trough_ratio,
                },
            ))

        return findings
