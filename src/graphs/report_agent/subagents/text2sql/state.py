from typing import Any, Dict, List, Optional, TypedDict


class Text2SQLState(TypedDict, total=False):
    """
    Text2SQL subagent state.

    Overlapping keys (LangGraph otomatik parent ReportState ile sync eder):
        user_query, query_type, active_sql, active_filters,
        sql_queries, results, error, active_results

    Internal keys (sadece bu subgraph içinde kullanılır):
        query_schema, schema_validation, auto_rules, term_filters, term_hints,
        candidate_filter_terms, validated_term_filters, retry_count, sql_error
    """

    # --- ReportState overlapping ---
    user_query: str
    query_type: Optional[str]
    active_sql: Optional[str]
    active_filters: Optional[List[Dict[str, Any]]]
    sql_queries: Optional[List[str]]
    pre_built_sql: Optional[str]        # modify_sql çıktısı — sql_generator bunu görünce yeniden üretmez
    results: Optional[List[Dict[str, Any]]]
    error: Optional[str]
    active_results: Optional[List[Dict[str, Any]]]

    # --- Internal ---
    query_schema:      Optional[Dict[str, Any]]       # QuerySchema.model_dump()
    schema_validation: Optional[Dict[str, Any]]       # schema_validator → SchemaValidationResult.model_dump()
    auto_rules:        Optional[List[Dict[str, Any]]] # ChromaDB'den bulunan rules — sql_generator uygular
    term_filters:      Optional[List[Dict[str, Any]]] # term_resolver → sql_generator (Python garantili WHERE)
    term_hints:        Optional[str]                  # term_resolver → sql_architect + schema_validator
    candidate_filter_terms: Optional[List[Dict[str, Any]]]  # term_resolver → term_validator (term_id + metadata)
    validated_term_filters: Optional[List[Dict[str, Any]]]  # term_validator → sql_generator (onaylanan filtreler)
    retry_count:       int                            # 0 | 1 | 2
    sql_error:         Optional[str]                  # Son SQL hata mesajı (retry için)
    # business_rules_context KALDIRILDI — LLM artık kuralları görmüyor
