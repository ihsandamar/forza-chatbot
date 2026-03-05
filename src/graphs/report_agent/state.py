from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ReportState(TypedDict):
    # Core
    messages: Annotated[List[BaseMessage], add_messages]
    user_query: str
    session_id: Optional[str]

    # Intent Classification (tek LLM çağrısı)
    intent_type: Optional[str]         # NEW_QUERY | MODIFY_QUERY | USE_RESULT | VAGUE_QUERY
    query_type: Optional[str]          # SINGLE | RANKING | COMPARISON | TIME_SERIES_COMPARISON
    intent_confidence: Optional[float]
    wants_visualization: Optional[bool]  # Kullanıcı açıkça grafik istedi mi?
    use_result_type: Optional[str]     # "new_query" | "revisualize" | "compute" | "modify_context"
    compute_operation: Optional[str]   # "sum" | "avg" | "count" | "min" | "max" (compute için)

    # Conversation Context (MODIFY ve USE_RESULT için)
    active_sql: Optional[str]
    active_results: Optional[List[Dict[str, Any]]]
    active_filters: Optional[List[Dict[str, Any]]]

    # Text2SQL I/O (subgraph shared fields)
    sql_queries: Optional[List[str]]
    pre_built_sql: Optional[str]        # modify_sql çıktısı — sql_generator bunu görünce yeniden üretmez
    _force_table_refresh: Optional[bool]  # True = DROP + recreate master table
    modification_hints: Optional[List[Dict[str, Any]]]  # modify_sql → value_resolver (MODIFY_QUERY value resolution)
    results: Optional[List[Dict[str, Any]]]
    error: Optional[str]
    candidate_filter_terms: Optional[List[Dict[str, Any]]]  # term_resolver → term_validator (term_id + metadata)
    validated_term_filters: Optional[List[Dict[str, Any]]]  # term_validator → sql_generator (onaylanan filtreler)

    # Visualization
    viz_request: Optional[str]           # "pasta grafik" gibi görselleştirme tarzı (sadece revisualize'da)
    visualization_output: Optional[Dict[str, Any]]

    # Clarification (VAGUE_QUERY loop protection)
    _clarification_count: Optional[int]  # report_chat geçiş sayısı, max 2
    _skip_vague_check: Optional[bool]    # True = max clarification aşıldı, VAGUE_QUERY → NEW_QUERY zorla

    # Response
    final_response: Optional[str]


def create_initial_state() -> ReportState:
    return ReportState(
        messages=[],
        user_query="",
        session_id=None,
        intent_type=None,
        query_type=None,
        intent_confidence=None,
        wants_visualization=None,
        use_result_type=None,
        compute_operation=None,
        active_sql=None,
        active_results=None,
        active_filters=None,
        sql_queries=None,
        pre_built_sql=None,
        modification_hints=None,
        results=None,
        error=None,
        candidate_filter_terms=None,
        validated_term_filters=None,
        viz_request=None,
        visualization_output=None,
        _clarification_count=0,
        _skip_vague_check=False,
        final_response=None,
    )
