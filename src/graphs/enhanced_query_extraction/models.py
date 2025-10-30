"""
Models and data structures for Enhanced Query Extraction Graph
"""
from typing import Dict, Any, List, Optional, TypedDict
from pydantic import BaseModel, Field
from typing import Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage


class EnhancedText2SQLState(TypedDict):
    """Enhanced state for multi-agent SQL generation workflow"""
    messages: Annotated[List[AnyMessage], add_messages]
    current_agent: Optional[str]
    table_info: Optional[Dict[str, Any]]
    context_data: Optional[Dict[str, Any]]
    intent_data: Optional[Dict[str, Any]]
    sql_parameters: Optional[Dict[str, Any]]
    generated_sql: Optional[str]
    execution_result: Optional[str]
    extraction_result: Optional[str]
    analysis_result: Optional[str]
    sql_generation_response: Optional[str]
    raw_llm_response: Optional[str]
    errors: Optional[Dict[str, str]]
    agent_results: Optional[Dict[str, Any]]


class Table(BaseModel):
    """Table schema model with column definitions and relations"""
    name: str = Field(description="Table name")
    columns: List[Dict[str, Any]] = Field(default=[], description="Column definitions with distinct values")
    relations: List[Dict[str, Any]] = Field(default=[], description="Table relationships")
    
    model_config = {"extra": "forbid"}


class BusinessTermsMapping(BaseModel):
    """Business terms semantic mapping configuration"""
    category: str = Field(description="Business term category")
    terms: List[str] = Field(description="List of synonymous terms")
    confidence_threshold: float = Field(default=0.7, description="Minimum confidence for matching")


class SQLParameter(BaseModel):
    """SQL parameter extraction result"""
    column: str = Field(description="Target column name")
    value: str = Field(description="Matched value")
    match_type: str = Field(description="Type of match: direct, semantic, fuzzy")
    confidence: float = Field(description="Match confidence score")
    semantic_term: Optional[str] = Field(default=None, description="Original semantic term if applicable")


class ConversationFlow(BaseModel):
    """Conversation flow analysis result"""
    conversation_type: str = Field(description="Type of conversation: new_query, follow_up, drill_down, etc.")
    confidence: float = Field(description="Confidence in classification")
    has_previous_results: bool = Field(default=False, description="Whether previous results exist")
    entity_continuity: List[str] = Field(default=[], description="Entities that continue from previous context")
    reasoning: str = Field(description="Reasoning for classification")