from collections import defaultdict
from typing import List

from src.graphs.report_agent.insight_engine.models import Finding

SIGNIFICANCE_THRESHOLD = 0.15  # aligned with lowest analyzer trigger
TOP_N = 12
MAX_PER_TYPE = 3


class FindingsRanker:
    def rank(self, findings: List[Finding]) -> List[Finding]:
        filtered = [f for f in findings if f.significance >= SIGNIFICANCE_THRESHOLD]
        sorted_findings = sorted(filtered, key=lambda f: f.significance, reverse=True)
        type_counts: dict = defaultdict(int)
        diverse = []
        for f in sorted_findings:
            if type_counts[f.type] < MAX_PER_TYPE:
                diverse.append(f)
                type_counts[f.type] += 1
        return diverse[:TOP_N]
