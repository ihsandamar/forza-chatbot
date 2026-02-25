from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ReportState(TypedDict):
    # Core
    messages: Annotated[List[BaseMessage], add_messages]
    user_query: str
    session_id: Optional[str]

    # Intent Classification (tek LLM çağrısı)
    intent_type: Optional[str]         # NEW_QUERY | MODIFY_QUERY | USE_RESULT
    query_type: Optional[str]          # SINGLE | RANKING | COMPARISON | TIME_SERIES_COMPARISON
    intent_confidence: Optional[float]
    wants_visualization: Optional[bool]  # Kullanıcı açıkça grafik istedi mi?
    use_result_type: Optional[str]     # "new_query" | "revisualize"

    # Conversation Context (MODIFY ve USE_RESULT için)
    active_sql: Optional[str]
    active_results: Optional[List[Dict[str, Any]]]
    active_filters: Optional[List[Dict[str, Any]]]

    # Text2SQL I/O (subgraph shared fields)
    sql_queries: Optional[List[str]]
    results: Optional[List[Dict[str, Any]]]
    error: Optional[str]

    # Visualization
    viz_request: Optional[str]           # "pasta grafik" gibi görselleştirme tarzı (sadece revisualize'da)
    visualization_output: Optional[Dict[str, Any]]

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
        active_sql=None,
        active_results=None,
        active_filters=None,
        sql_queries=None,
        results=None,
        error=None,
        viz_request=None,
        visualization_output=None,
        final_response=None,
    )
