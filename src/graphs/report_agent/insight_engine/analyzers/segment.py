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

        findings.extend(self._bcg_analysis(current_df, comparison_df, context))
        return findings

    def _bcg_analysis(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        if comparison_df.empty:
            return []
        dim_cols = [c for c in context.dimension_columns if c in current_df.columns and c in comparison_df.columns]
        metric_cols = [c for c in context.metric_columns if c in current_df.columns and c in comparison_df.columns]
        if not dim_cols or not metric_cols:
            return []

        dim = dim_cols[0]
        metric = metric_cols[0]
        cur = current_df.groupby(dim)[metric].sum().reset_index()
        comp = comparison_df.groupby(dim)[metric].sum().reset_index()
        merged = cur.merge(comp.rename(columns={metric: f"{metric}_prev"}), on=dim, how="inner")
        if len(merged) < 4:
            return []

        merged[metric] = merged[metric].astype(float)
        merged[f"{metric}_prev"] = merged[f"{metric}_prev"].astype(float)
        merged["growth"] = merged.apply(
            lambda r: (r[metric] - r[f"{metric}_prev"]) / r[f"{metric}_prev"] * 100
            if r[f"{metric}_prev"] != 0 else 0.0,
            axis=1,
        )
        total = float(merged[metric].sum())
        if total == 0:
            return []
        merged["share"] = merged[metric] / total

        growth_median = float(merged["growth"].median())
        share_median = float(merged["share"].median())

        _BCG = {
            (True, True): "bcg_star",
            (False, True): "bcg_cash_cow",
            (True, False): "bcg_question_mark",
            (False, False): "bcg_dog",
        }
        _BASE_SIG = {"bcg_star": 0.5, "bcg_dog": 0.4, "bcg_cash_cow": 0.35, "bcg_question_mark": 0.3}
        raw: List[Finding] = []
        for _, row in merged.iterrows():
            is_hg = row["growth"] > growth_median
            is_hs = row["share"] > share_median
            bcg_type = _BCG[(is_hg, is_hs)]
            growth_excess = abs(float(row["growth"]) - growth_median) / (abs(growth_median) + 1)
            share_excess = abs(float(row["share"]) - share_median) / (share_median + 0.01)
            sig = round(min(_BASE_SIG[bcg_type] + (growth_excess + share_excess) * 0.05, 1.0), 3)
            raw.append(Finding(
                type=bcg_type,
                analyzer=self.name,
                dimension=dim,
                value=str(row[dim]),
                metric=metric,
                current_value=round(float(row[metric]), 2),
                comparison_value=round(float(row[f"{metric}_prev"]), 2),
                change_pct=round(float(row["growth"]), 2),
                significance=sig,
                period_label=context.period_label,
                extra={
                    "growth_pct": round(float(row["growth"]), 2),
                    "revenue_share_pct": round(float(row["share"]) * 100, 2),
                    "vs_avg_growth": round(float(row["growth"]) - growth_median, 2),
                },
            ))
        # Keep top 1 per BCG type (most significant)
        seen_types: set = set()
        result: List[Finding] = []
        for f in sorted(raw, key=lambda f: f.significance, reverse=True):
            if f.type not in seen_types:
                result.append(f)
                seen_types.add(f.type)
        return result
