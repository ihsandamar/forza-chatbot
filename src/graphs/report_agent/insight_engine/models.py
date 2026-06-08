from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AnalysisContext:
    user_query: str
    active_filters: List[Dict[str, Any]]
    period_label: str
    dimension_columns: List[str]
    metric_columns: List[str]


@dataclass
class Finding:
    type: str
    analyzer: str
    dimension: str
    value: str
    metric: str
    current_value: float
    comparison_value: float
    change_pct: float
    significance: float
    period_label: str
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "analyzer": self.analyzer,
            "dimension": self.dimension,
            "value": self.value,
            "metric": self.metric,
            "current_value": self.current_value,
            "comparison_value": self.comparison_value,
            "change_pct": round(self.change_pct, 2),
            "significance": round(self.significance, 3),
            "period_label": self.period_label,
            "extra": self.extra,
        }
