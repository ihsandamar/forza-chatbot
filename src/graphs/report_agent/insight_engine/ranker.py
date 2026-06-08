from typing import List

from src.graphs.report_agent.insight_engine.models import Finding

SIGNIFICANCE_THRESHOLD = 0.40
TOP_N = 8


class FindingsRanker:
    def rank(self, findings: List[Finding]) -> List[Finding]:
        filtered = [f for f in findings if f.significance >= SIGNIFICANCE_THRESHOLD]
        return sorted(filtered, key=lambda f: f.significance, reverse=True)[:TOP_N]
