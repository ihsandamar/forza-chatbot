from typing import Any, Dict, List, Optional, TypedDict


class Text2SQLState(TypedDict, total=False):
    """
    Text2SQL subagent state.

    Overlapping keys (LangGraph otomatik parent ReportState ile sync eder):
        user_query, query_type, active_sql, active_filters,
        sql_queries, results, error, active_results

    Internal keys (sadece bu subgraph içinde kullanılır):
        query_schema, business_rules_context, retry_count, sql_error
    """

    # --- ReportState overlapping ---
    user_query: str
    query_type: Optional[str]
    active_sql: Optional[str]
    active_filters: Optional[List[Dict[str, Any]]]
    sql_queries: Optional[List[str]]
    results: Optional[List[Dict[str, Any]]]
    error: Optional[str]
    active_results: Optional[List[Dict[str, Any]]]

    # --- Internal ---
    query_schema: Optional[Dict[str, Any]]     # QuerySchema.model_dump()
    business_rules_context: Optional[str]      # LLM için formatlı kural listesi
    retry_count: int                           # 0 | 1 | 2
    sql_error: Optional[str]                   # Son SQL hata mesajı (retry için)
