import logging
from typing import List

import numpy as np
import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

CORR_THRESHOLD = 0.75
MIN_TIME_PERIODS = 7
MAX_CATEGORIES = 10
MAX_FINDINGS = 5
_DATE_COLUMNS = {"DocumentDate"}


class CorrelationAnalyzer(BaseAnalyzer):
    @property
    def name(self) -> str:
        return "CorrelationAnalyzer"

    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        date_cols = [c for c in context.dimension_columns if c in _DATE_COLUMNS and c in current_df.columns]
        cat_cols = [c for c in context.dimension_columns if c not in _DATE_COLUMNS and c in current_df.columns]
        metric_cols = [c for c in context.metric_columns if c in current_df.columns]
        if not date_cols or not cat_cols or not metric_cols:
            return findings

        date_col = date_cols[0]
        cat_col = cat_cols[0]
        metric = metric_cols[0]

        df = current_df[[date_col, cat_col, metric]].copy()
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        df[metric] = df[metric].astype(float)

        pivot = df.groupby([date_col, cat_col])[metric].sum().unstack(fill_value=0)

        if pivot.shape[0] < MIN_TIME_PERIODS or pivot.shape[1] < 2:
            return findings

        # Limit to top MAX_CATEGORIES by total metric value
        top_cats = pivot.sum().nlargest(MAX_CATEGORIES).index.tolist()
        pivot = pivot[top_cats]
        categories = pivot.columns.tolist()

        raw_findings: List[Finding] = []
        for i in range(len(categories)):
            for j in range(i + 1, len(categories)):
                col_a = categories[i]
                col_b = categories[j]
                vals_a = pivot[col_a].values.astype(float)
                vals_b = pivot[col_b].values.astype(float)
                if float(np.std(vals_a)) == 0 or float(np.std(vals_b)) == 0:
                    continue
                corr_matrix = np.corrcoef(vals_a, vals_b)
                r = float(corr_matrix[0, 1])
                if np.isnan(r) or abs(r) < CORR_THRESHOLD:
                    continue
                finding_type = "high_positive_correlation" if r > 0 else "high_negative_correlation"
                significance = round(min((abs(r) - 0.5) * 2.0, 1.0), 3)
                raw_findings.append(Finding(
                    type=finding_type,
                    analyzer=self.name,
                    dimension=cat_col,
                    value=f"{col_a} ↔ {col_b}",
                    metric=metric,
                    current_value=round(float(np.mean(vals_a)), 2),
                    comparison_value=round(float(np.mean(vals_b)), 2),
                    change_pct=0.0,
                    significance=significance,
                    period_label=context.period_label,
                    extra={
                        "r": round(r, 4),
                        "product_a": str(col_a),
                        "product_b": str(col_b),
                        "n_periods": int(pivot.shape[0]),
                    },
                ))

        return sorted(raw_findings, key=lambda f: f.significance, reverse=True)[:MAX_FINDINGS]
