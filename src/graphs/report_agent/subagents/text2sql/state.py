from typing import Any, Dict, List, Optional, TypedDict


class Text2SQLState(TypedDict, total=False):
    """
    Text2SQL subagent state.

    Overlapping keys (LangGraph otomatik parent ReportState ile sync eder):
        user_query, query_type, active_sql, active_filters,
        sql_queries, results, error, active_results

    Internal keys (sadece bu subgraph içinde kullanılır):
        query_schema, auto_rules, term_filters,
        candidate_filter_terms, validated_term_filters, retry_count, sql_error,
        semantic_intent, term_resolution, time_breakdown
    """

    # --- ReportState overlapping ---
    user_query: str
    query_type: Optional[str]
    active_sql: Optional[str]
    active_filters: Optional[List[Dict[str, Any]]]
    sql_queries: Optional[List[str]]
    pre_built_sql: Optional[str]        # modify_sql çıktısı — sql_generator bunu görünce yeniden üretmez
    time_granularity: Optional[str]      # → ReportState → VisualizationState
    comparison_dimension: Optional[str]   # sql_generator → parent ReportState → viz
    modification_hints: Optional[List[Dict[str, Any]]]  # modify_sql → value_resolver (MODIFY_QUERY value resolution)
    results: Optional[List[Dict[str, Any]]]
    error: Optional[str]
    active_results: Optional[List[Dict[str, Any]]]
    text2sql_clarification: Optional[dict]   # node → parent (sinyal)
    text2sql_answers: Optional[list]         # parent → node (cevaplar)

    # --- Internal ---
    query_schema:      Optional[Dict[str, Any]]       # QuerySchema.model_dump()
    # schema_validation KALDIRILDI — schema_validator node kaldırıldı
    auto_rules:        Optional[List[Dict[str, Any]]] # ChromaDB'den bulunan rules — sql_generator uygular
    term_filters:      Optional[List[Dict[str, Any]]] # term_resolver → sql_generator (Python garantili WHERE)
    # term_hints KALDIRILDI — semantic_intent / term_resolution ile değiştirildi
    candidate_filter_terms: Optional[List[Dict[str, Any]]]  # term_resolver → term_validator (term_id + metadata)
    validated_term_filters: Optional[List[Dict[str, Any]]]  # term_validator → sql_generator (onaylanan filtreler)
    retry_count:       int                            # 0 | 1 | 2
    sql_error:         Optional[str]                  # Son SQL hata mesajı (retry için)
    # business_rules_context KALDIRILDI — LLM artık kuralları görmüyor

    # --- NLU Pipeline (semantic approach) ---
    semantic_intent:   Optional[Dict]                 # SemanticIntent.model_dump() — semantic_extractor output
    term_resolution:   Optional[Dict]                 # {raw_text → TermMatch dict} — term_resolver output
    time_breakdown:    Optional[bool]                 # intent_resolver time_breakdown flag passed into subgraph
