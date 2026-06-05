from typing import Optional, TypedDict


class QueryClarifierState(TypedDict, total=False):
    # Parent ReportState ile örtüşen anahtarlar (otomatik senkronize edilir)
    user_query: str
    intent_type: Optional[str]        # NEW_QUERY | MODIFY_QUERY | VAGUE_QUERY
    active_sql: Optional[str]         # MODIFY_QUERY bağlamı için

    # Subgraph çıktıları — parent ReportState'e yazılır
    clarifier_decision: Optional[str]  # PASS | CLARIFIED
    suggested_query: Optional[str]     # Kabul edilirse user_query'yi replace eder
