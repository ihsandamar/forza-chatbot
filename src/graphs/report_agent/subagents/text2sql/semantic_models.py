from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


class SemanticEntity(BaseModel):
    raw_text: str
    entity_type: Literal["filter_value", "dimension", "comparison_value"]
    column_hint: Optional[str] = None


class SemanticMetric(BaseModel):
    raw_text: str
    aggregation_hint: Literal["SUM", "COUNT", "AVG", "MAX", "MIN"]


class SemanticTime(BaseModel):
    raw_text: str
    breakdown: bool  # True = GROUP BY kırılımı, False = WHERE filtresi
    granularity: Optional[Literal[
        "monthly", "weekly", "daily", "yearly", "hourly",
        "hour_of_day", "day_of_week", "day_of_month",
    ]] = None


class SemanticIntent(BaseModel):
    entities: List[SemanticEntity] = []
    metrics: List[SemanticMetric] = []
    time: Optional[SemanticTime] = None
    limit: Optional[int] = None
    order_direction: Literal["ASC", "DESC"] = "DESC"
    raw_query: str = ""


@dataclass
class TermMatch:
    column_name: str
    filter_structured: Optional[Dict]
    specificity: float
    similarity: float
