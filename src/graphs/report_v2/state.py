"""
OrchestratorState — Report V2 Network Architecture

Thin coordination bus.
Agent'lar kendi TypedDict state'lerini kullanır;
bu modül sadece agent çıktılarının typed contract'larını ve
orchestrator'ın coordination alanlarını tanımlar.
"""

from typing import TypedDict, List, Optional, Dict, Any, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# Korunan state tipleri — DEĞİŞMEZ
from src.graphs.report.state import (
    ActiveQueryContext,
    QueryCheckpoint,
    PendingQuestion,
    BusinessContext,
    checkpoint_reducer,
    create_empty_context,
    create_checkpoint,
)


class ClassifyResult(TypedDict):
    intent_type: str
    query_type: str
    confidence: float
    needs_clarification: bool
    pending_question: Optional[PendingQuestion]
    user_query: str
    entities: Optional[Dict[str, Any]]
    reference_context: Optional[Dict[str, Any]]


class SQLResult(TypedDict):
    results: List[Dict[str, Any]]
    sql_query: str
    no_records_message: Optional[str]
    updated_active_context: Optional[ActiveQueryContext]
    conversation_entry: Optional[Dict[str, Any]]
    error: Optional[str]


class AnalysisResult(TypedDict):
    should_visualize: bool
    viz_decision: Dict[str, Any]
    business_insights: Optional[BusinessContext]
    viz_reasoning: Optional[str]


class OrchestratorState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    user_input: str
    session_id: Optional[str]
    conversation_history: List[Dict[str, Any]]
    active_context: Optional[ActiveQueryContext]
    query_history: Annotated[List[QueryCheckpoint], checkpoint_reducer]
    clarification_count: int
    user_clarification: Optional[str]
    classify_result: Optional[ClassifyResult]
    sql_result: Optional[SQLResult]
    analysis_result: Optional[AnalysisResult]
    viz_artifact: Optional[Dict[str, Any]]
    error: Optional[str]
    final_response: Optional[str]


def create_initial_state(user_input: str, session_id: Optional[str] = None) -> OrchestratorState:
    return OrchestratorState(
        messages=[],
        user_input=user_input,
        session_id=session_id,
        conversation_history=[],
        active_context=None,
        query_history=[],
        clarification_count=0,
        user_clarification=None,
        classify_result=None,
        sql_result=None,
        analysis_result=None,
        viz_artifact=None,
        error=None,
        final_response=None,
    )
