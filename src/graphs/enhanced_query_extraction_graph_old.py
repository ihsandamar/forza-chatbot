#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# src/graphs/enhanced_query_extraction_graph.py
"""
Enhanced Query Extraction Graph - Multi-Agent Architecture
SQL tablo şemasını çeker ve gelişmiş intent analizi yapar
"""

import time
import re
import json
from typing import Dict, Any, List, Optional, TypedDict
from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langchain_community.utilities import SQLDatabase
from langchain_community.tools.sql_database.tool import QuerySQLDatabaseTool
from langchain_core.tools import tool
from langchain_core.messages import ToolMessage, AnyMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field
from typing import Annotated
from langgraph.graph.message import add_messages

from src.graphs.base_graph import BaseGraph
from src.graphs.registry import register_graph
from src.services.app_logger import log
from src.graphs.generic_sql_graph import SQLAgentConfiguration
from src.services.config_loader import ConfigLoader
from src.config.business_terms_config import business_config


config = ConfigLoader.load_config("config/config.yaml")


class EnhancedText2SQLState(TypedDict):
    """State for Enhanced Query Extraction Multi-Agent workflow"""
    messages: Annotated[list[AnyMessage], add_messages]
    table_info: Optional[Dict[str, Any]]
    extraction_result: Optional[str]
    errors: Optional[Dict[str, Any]]
    intent_analysis: Optional[Dict[str, Any]]
    analysis_result: Optional[str]
    context_analysis: Optional[Dict[str, Any]]
    sql_parameters: Optional[Dict[str, Any]]
    distinct_value_matches: Optional[Dict[str, Any]]
    current_agent: Optional[str]
    agent_results: Optional[Dict[str, Any]]


class Table(BaseModel):
    """Table schema model with column definitions and relations"""
    name: str = Field(description="Name of table in SQL database")
    columns: List[Dict[str, Any]] = Field(default=[], description="Column definitions with distinct values")
    relations: List[str] = Field(default=[], description="Table relations")


# Tools for Multi-Agent Architecture
@tool
def context_analysis_tool(messages: List[AnyMessage], max_tokens: int = 1500) -> Dict:
    """Tool for analyzing conversation context and extracting relevant information"""
    
    def estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def extract_key_entities(msgs: List[AnyMessage]) -> List[str]:
        entities = set()
        for msg in msgs:
            content = msg.content
            if isinstance(content, list):
                content = ' '.join(str(item) for item in content)
            content = str(content).upper()
            words = content.split()
            for word in words:
                if len(word) > 2 and (word.isupper() or word.isdigit()):
                    entities.add(word)
        return list(entities)[:5]

    def extract_topics(msgs: List[AnyMessage]) -> List[str]:
        topics = set()
        business_keywords = ['satış', 'müşteri', 'ürün', 'fatura', 'sipariş', 'stok', 'personel', 'departman']
        for msg in msgs:
            content = msg.content
            if isinstance(content, list):
                content = ' '.join(str(item) for item in content)
            content = str(content).lower()
            for keyword in business_keywords:
                if keyword in content:
                    topics.add(keyword)
        return list(topics)[:3]

    def detect_conversation_flow(msgs: List[AnyMessage]) -> Dict:
        flow_indicators = {
            "pronoun_references": [],
            "query_references": [],
            "flow_words": [],
            "topic_continuity": False,
            "entity_continuity": [],
            "has_previous_results": False,
            "domain_continuity": False
        }
        
        if not msgs:
            return flow_indicators
        
        current_content = msgs[-1].content
        current_content = extract_plain_text_from_message(current_content).lower()
        
        # Enhanced context reference detection
        pronouns = ["bunların", "onların", "şunların", "olanın", "olan", "bunun", "onun"]
        query_refs = ["aynı sorguyu", "ayni sorguyu", "o sorguyu", "benzer sorguyu", "önceki sorgu", "geçen sorgu"]
        flow_words = ["peki", "şimdi", "sonra", "ayrıca", "de", "da", "bir de"]
        
        flow_indicators["pronoun_references"] = [p for p in pronouns if p in current_content]
        flow_indicators["query_references"] = [q for q in query_refs if q in current_content]
        flow_indicators["flow_words"] = [w for w in flow_words if w in current_content]
        
        # AI-powered previous SQL results detection
        def detect_previous_sql_results(messages: List[AnyMessage]) -> bool:
            for msg in reversed(messages):
                # Check message type properly
                msg_type = getattr(msg, 'type', None)
                if msg_type:
                    # Check for tool messages with SQL results
                    if msg_type == 'tool':
                        content = str(getattr(msg, 'content', '')).upper()
                        if any(pattern in content for pattern in ['SELECT', 'FROM', 'WHERE', 'ROWS RETURNED', 'QUERY EXECUTED']):
                            return True
                    # Check for AI messages containing SQL
                    elif msg_type == 'ai':
                        content = str(getattr(msg, 'content', '')).upper()
                        if 'SELECT' in content and 'FROM' in content:
                            return True
                        # Also check for SQL generation indicators
                        if any(indicator in content for indicator in ['SQL GENERATION', 'SQL PARAMETER', 'COUNT(*) FROM']):
                            return True
            return False
        
        flow_indicators["has_previous_results"] = detect_previous_sql_results(msgs)
        
        # Domain continuity analysis
        if len(msgs) > 1:
            prev_content = msgs[-2].content if len(msgs) > 1 else ""
            prev_content = extract_plain_text_from_message(prev_content).lower()
            
            # Business domain terms
            domain_terms = ['cari', 'kdv', 'istisna', 'tutar', 'belge', 'fatura', 'müşteri', 'grup', 'toplam']
            
            current_domains = [term for term in domain_terms if term in current_content]
            prev_domains = [term for term in domain_terms if term in prev_content]
            
            common_domains = set(current_domains) & set(prev_domains)
            flow_indicators["domain_continuity"] = len(common_domains) > 0
            
            # Entity continuity
            common_words = set(current_content.split()) & set(prev_content.split())
            business_words = [w for w in common_words if len(w) > 3 and w not in ["olan", "için", "nedir", "ile", "dan", "den"]]
            flow_indicators["entity_continuity"] = list(business_words)
            flow_indicators["topic_continuity"] = len(business_words) > 0
        
        return flow_indicators

    context_result = {
        "current_message": "",
        "recent_context": [],
        "conversation_summary": "",
        "flow_indicators": {},
        "total_tokens": 0
    }
    
    if not messages:
        return context_result
    
    # Current message analysis
    current_msg = messages[-1]
    current_content = current_msg.content
    
    # Smart message content extraction - handle both formats
    def extract_plain_text_from_message(content):
        if isinstance(content, list):
            # Handle list format: [{"type": "text", "text": "..."}] or ["text1", "text2"]
            text_parts = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    text_parts.append(str(item["text"]))
                elif isinstance(item, str):
                    text_parts.append(item)
                else:
                    text_parts.append(str(item))
            return ' '.join(text_parts)
        elif isinstance(content, str):
            return content
        else:
            return str(content)
    
    context_result["current_message"] = extract_plain_text_from_message(current_content)
    current_tokens = estimate_tokens(str(current_content))
    context_result["total_tokens"] += current_tokens
    
    # Recent context extraction
    recent_messages = []
    token_budget = max_tokens * 0.7
    
    for msg in reversed(messages[:-1]):
        msg_content = msg.content
        if isinstance(msg_content, list):
            msg_content = ' '.join(str(item) for item in msg_content)
        msg_tokens = estimate_tokens(str(msg_content))
        if context_result["total_tokens"] + msg_tokens > token_budget:
            break
        recent_messages.insert(0, msg)
        context_result["total_tokens"] += msg_tokens
        
        if len(recent_messages) >= 8:
            break
    
    context_result["recent_context"] = recent_messages
    
    # Conversation summary for older messages
    remaining_budget = max_tokens - context_result["total_tokens"]
    older_messages = messages[:-len(recent_messages)-1]
    
    if older_messages and remaining_budget > 300:
        entities = extract_key_entities(older_messages)
        topics = extract_topics(older_messages)
        summary = f"Önceki konuşma: {', '.join(topics)} konularında {', '.join(entities)} hakkında sorular."
        
        if estimate_tokens(summary) > remaining_budget:
            summary = summary[:remaining_budget*4]
        
        context_result["conversation_summary"] = summary
        context_result["total_tokens"] += estimate_tokens(summary)
    
    # Flow analysis
    context_result["flow_indicators"] = detect_conversation_flow(
        recent_messages + [current_msg]
    )
    
    return context_result


@tool
def prompt_builder_tool(context_data: Dict, table_info: Dict) -> str:
    """Tool for building enhanced context-aware prompts"""
    
    current_msg = context_data["current_message"]
    recent_context = context_data["recent_context"] 
    conversation_summary = context_data["conversation_summary"]
    flow_indicators = context_data["flow_indicators"]
    
    # Table context
    table_context = ""
    if table_info and table_info.get("columns"):
        searchable_columns = [
            col["name"] for col in table_info["columns"] 
            if col.get("distinct_values")
        ]
        table_context = f"Aranabilir kolonlar: {', '.join(searchable_columns[:10])}"
    
    # Recent conversation context
    recent_context_text = ""
    if recent_context:
        for i, msg in enumerate(recent_context):
            msg_type = "Kullanıcı" if isinstance(msg, HumanMessage) else "Asistan"
            msg_content = msg.content
            if isinstance(msg_content, list):
                msg_content = ' '.join(str(item) for item in msg_content)
            recent_context_text += f"{i+1}. {msg_type}: {str(msg_content)[:100]}...\n"
    
    # Flow analysis
    flow_analysis = ""
    if flow_indicators["pronoun_references"]:
        flow_analysis += f"Pronoun referansları: {flow_indicators['pronoun_references']}\n"
    if flow_indicators["flow_words"]:
        flow_analysis += f"Akış kelimeleri: {flow_indicators['flow_words']}\n"
    if flow_indicators["topic_continuity"]:
        flow_analysis += f"Konu devamı: {flow_indicators['entity_continuity']}\n"
    
    return f"""ERP CHATBOT - CONTEXT-AWARE INTENT ANALYSIS

==== CONVERSATION CONTEXT ====
{conversation_summary}

Son Konuşma:
{recent_context_text}

Mevcut Kullanıcı Mesajı: "{current_msg}"

==== CONTEXT ANALYSIS ====
{flow_analysis}

==== TABLE CONTEXT ====  
{table_context}

==== INTENT CLASSIFICATION RULES ====
Intent Türleri:
• count: Sayım ("kaç tane", "sayısı", "adet")
• sum: Toplama ("toplam", "total tutar", "toplamı")  
• list: Listeleme ("göster", "hangileri", "listele")
• group: Gruplama ("kategoriye göre", "dağılım", "gruplayarak")
• filter: Filtreleme ("şartını sağlayan", "kriterlere uygun")
• compare: Karşılaştırma ("farkı", "hangisi daha", "karşılaştır")
• trend: Trend analizi ("seyre git", "artış", "azalış")

Konuşma Türleri:
• new_query: Tamamen yeni konu
• follow_up: Önceki soruyla ilgili ("bunların toplamı", "peki listeler misin")
• drill_down: Önceki sonuçlarda detaya inme ("DOĞALGAZ olanların detayı")
• refinement: Kapsam değişikliği ("bu ay" → "son 3 ay")
• clarification: Belirsizlik giderme ("hangi ABC firması")
• comparison_extension: Karşılaştırma ekleme

==== CONTEXT CLUES DECISION MATRIX ====
PRIORITY 1 - Query References:
"aynı sorguyu", "benzer sorguyu", "o sorguyu" → ALWAYS refinement

PRIORITY 2 - Previous Results + Context:
has_previous_results + ("olan", "olanın") + entity_continuity → drill_down

PRIORITY 3 - Flow Continuity:
flow_words + entity_continuity + domain_continuity → follow_up/refinement

PRIORITY 4 - Entity Continuity:
entity_continuity + NO pronoun_references + domain_continuity → refinement

PRIORITY 5 - Default:
No clear context → new_query

==== REQUIRED OUTPUT FORMAT ====
{{
    "intent_type": "count|sum|list|group|filter|compare|trend",
    "conversation_type": "new_query|follow_up|drill_down|refinement|clarification|comparison_extension", 
    "confidence": 0.0-1.0,
    "target_action": "ne yapmaya çalışıyor - kısa açıklama",
    "reasoning": "karar verme süreci açıklaması",
    "requires_context": true/false,
    "context_references": ["hangi kelimelere referans veriyor"],
    "suggested_entities": ["potansiyel entity'ler tabloda aranacak"]
}}

ANALYSIS:"""


@tool
def response_parser_tool(llm_response: str, context_data: Dict) -> Dict:
    """Tool for parsing and validating LLM responses with fallback logic"""
    
    def parse_json_response(response: str) -> Dict:
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                analysis = json.loads(json_match.group())
            else:
                raise ValueError("JSON bulunamadı")
            
            required_fields = ["intent_type", "conversation_type", "confidence"]
            defaults = {
                "intent_type": "list",
                "conversation_type": "new_query", 
                "confidence": 0.5,
                "target_action": "Varsayılan analiz",
                "reasoning": "Eksik alan için varsayılan değer",
                "requires_context": False,
                "context_references": [],
                "suggested_entities": []
            }
            
            for field in required_fields:
                if field not in analysis:
                    analysis[field] = defaults.get(field)
            
            confidence = float(analysis.get("confidence", 0.5))
            analysis["confidence"] = max(0.0, min(1.0, confidence))
            
            return analysis
            
        except Exception as e:
            return {
                "intent_type": "list",
                "conversation_type": "new_query",
                "confidence": 0.3,
                "target_action": "Parsing hatası nedeniyle varsayılan analiz",
                "reasoning": f"LLM response parse edilemedi: {str(e)}",
                "requires_context": False,
                "context_references": [],
                "suggested_entities": []
            }
    
    def apply_fallback_logic(analysis: Dict, context: Dict) -> Dict:
        current_msg = context["current_message"]
        if isinstance(current_msg, list):
            current_msg = ' '.join(str(item) for item in current_msg)
        current_msg = str(current_msg).lower()
        flow_indicators = context["flow_indicators"]
        
        # Enhanced intent type classification
        if any(word in current_msg for word in ["kaç", "sayı", "adet"]):
            analysis["intent_type"] = "count"
            analysis["confidence"] = min(0.8, analysis["confidence"] + 0.3)
        elif any(word in current_msg for word in ["toplam", "total"]):
            analysis["intent_type"] = "sum" 
            analysis["confidence"] = min(0.8, analysis["confidence"] + 0.3)
        elif any(word in current_msg for word in ["göster", "listele"]):
            analysis["intent_type"] = "list"
            analysis["confidence"] = min(0.8, analysis["confidence"] + 0.3)
        elif any(word in current_msg for word in ["grup", "kategoriye", "dağılım"]):
            analysis["intent_type"] = "group"
            analysis["confidence"] = min(0.8, analysis["confidence"] + 0.3)
        
        # Enhanced conversation type classification with priority system
        classification_reasoning = []
        
        # PRIORITY 1: Query References (highest priority)
        if flow_indicators.get("query_references"):
            analysis["conversation_type"] = "refinement"
            analysis["confidence"] = min(0.9, analysis["confidence"] + 0.4)
            classification_reasoning.append(f"Query references detected: {flow_indicators['query_references']}")
        
        # PRIORITY 2: Previous Results + Context
        elif (flow_indicators.get("has_previous_results") and 
              flow_indicators.get("pronoun_references") and 
              flow_indicators.get("entity_continuity")):
            analysis["conversation_type"] = "drill_down"
            analysis["confidence"] = min(0.8, analysis["confidence"] + 0.3)
            classification_reasoning.append("Previous SQL results + context references + entity continuity")
        
        # PRIORITY 3: Flow Continuity
        elif (flow_indicators.get("flow_words") and 
              flow_indicators.get("entity_continuity") and 
              flow_indicators.get("domain_continuity")):
            if flow_indicators.get("domain_continuity"):
                analysis["conversation_type"] = "refinement"
            else:
                analysis["conversation_type"] = "follow_up"
            analysis["confidence"] = min(0.8, analysis["confidence"] + 0.2)
            classification_reasoning.append("Flow words + entity/domain continuity")
        
        # PRIORITY 4: Entity + Domain Continuity (High Confidence for Refinement)
        elif (flow_indicators.get("entity_continuity") and 
              flow_indicators.get("domain_continuity") and 
              len(flow_indicators.get("entity_continuity", [])) >= 2):
            analysis["conversation_type"] = "refinement"  
            analysis["confidence"] = min(0.85, analysis["confidence"] + 0.3)
            classification_reasoning.append(f"Strong entity continuity ({len(flow_indicators.get('entity_continuity', []))}) + domain continuity")
        
        # PRIORITY 5: Topic Continuity (Medium Confidence)
        elif (flow_indicators.get("topic_continuity") and 
              flow_indicators.get("domain_continuity")):
            analysis["conversation_type"] = "refinement"
            analysis["confidence"] = min(0.75, analysis["confidence"] + 0.2)
            classification_reasoning.append("Topic continuity + domain continuity")
        
        # PRIORITY 6: Basic flow indicators
        elif flow_indicators.get("pronoun_references") or flow_indicators.get("flow_words"):
            analysis["conversation_type"] = "follow_up"
            analysis["confidence"] = min(0.6, analysis["confidence"] + 0.1)
            classification_reasoning.append("Basic pronoun or flow word references")
        
        # Add classification reasoning
        if classification_reasoning:
            analysis["reasoning"] += f" (Enhanced classification: {'; '.join(classification_reasoning)})"
        else:
            analysis["reasoning"] += " (Fallback kuralları uygulandı)"
            
        return analysis
    
    analysis_result = parse_json_response(llm_response)
    
    if analysis_result["confidence"] < 0.6:
        analysis_result = apply_fallback_logic(analysis_result, context_data)
    
    return analysis_result


@tool
def table_data_extraction_tool(table_name: str, table_columns: List[Dict], max_distinct_values: int, db_connection: Any) -> Dict:
    """Tool for extracting and enriching table schema data with semantic entity matching"""
    
    def is_string_column(column_type: str) -> bool:
        string_types = ['varchar', 'text', 'char', 'string', 'nvarchar', 'ntext']
        return any(str_type in column_type.lower() for str_type in string_types)
    
    def semantic_entity_matching(distinct_values: List[str], user_terms: List[str]) -> Dict:
        """Perform semantic matching between user terms and distinct values"""
        matches = {}
        
        for user_term in user_terms:
            user_term_lower = user_term.lower()
            best_matches = []
            
            for value in distinct_values:
                value_lower = str(value).lower()
                
                # Exact match (highest score)
                if user_term_lower == value_lower:
                    best_matches.append({"value": value, "score": 1.0, "type": "exact"})
                
                # Contains match
                elif user_term_lower in value_lower or value_lower in user_term_lower:
                    score = min(len(user_term_lower), len(value_lower)) / max(len(user_term_lower), len(value_lower))
                    best_matches.append({"value": value, "score": score, "type": "contains"})
                
                # Fuzzy matching for Turkish terms
                elif user_term_lower in ['doğalgaz', 'dogalgaz', 'dogalgz'] and any(fuzzy in value_lower for fuzzy in ['dogalgaz', 'doğalgaz', 'gaz']):
                    best_matches.append({"value": value, "score": 0.8, "type": "fuzzy"})
                
                elif user_term_lower in ['elektrik', 'electric'] and any(fuzzy in value_lower for fuzzy in ['elektrik', 'electric', 'enerji']):
                    best_matches.append({"value": value, "score": 0.8, "type": "fuzzy"})
            
            # Sort by score and keep top matches
            best_matches.sort(key=lambda x: x["score"], reverse=True)
            if best_matches:
                matches[user_term] = best_matches[:3]  # Top 3 matches
        
        return matches
    
    try:
        execute_tool = QuerySQLDatabaseTool(db=db_connection)
        enriched_columns = []
        
        for config_col in table_columns:
            col_name = config_col.get("name", "") if isinstance(config_col, dict) else str(config_col)
            col_type = config_col.get("type", "") if isinstance(config_col, dict) else ""
            col_description = config_col.get("description", "") if isinstance(config_col, dict) else ""
            
            column_info = {
                "name": col_name,
                "type": col_type,
                "description": col_description,
                "distinct_values": [],
                "semantic_matches": {}
            }
            
            if col_name and is_string_column(col_type):
                try:
                    query = f"SELECT DISTINCT TOP {max_distinct_values} [{col_name}] FROM [{table_name}] WHERE [{col_name}] IS NOT NULL"
                    result = execute_tool.invoke(query)
                    
                    values = []
                    for line in result.split('\n'):
                        line = line.strip()
                        if line and not line.startswith('-') and not line.startswith('('):
                            values.append(line)
                    
                    column_info["distinct_values"] = values[:max_distinct_values]
                    
                    # Add semantic matching for common business terms from config
                    common_terms = business_config.get_common_terms()
                    if values:
                        column_info["semantic_matches"] = semantic_entity_matching(values, common_terms)
                    
                except Exception:
                    column_info["distinct_values"] = []
                    column_info["semantic_matches"] = {}
            
            enriched_columns.append(column_info)
        
        table_info = Table(
            name=table_name,
            columns=enriched_columns,
            relations=[]
        )
        
        return {
            "table_name": table_info.name,
            "columns": table_info.columns,
            "relations": table_info.relations,
            "semantic_matching_enabled": True
        }
        
    except Exception as e:
        raise Exception(f"Table data extraction failed: {str(e)}")


# Multi-Agent Classes
class TableDataAgent:
    """Specialized Agent for table data extraction and schema preparation"""
    
    def __init__(self, db: SQLDatabase, logger):
        self.db = db
        self.logger = logger
        
    def execute(self, state: EnhancedText2SQLState, *, config) -> EnhancedText2SQLState:
        """Execute table data extraction workflow"""
        state["current_agent"] = "table_data_agent"
        
        try:
            configurable = config.get("configurable", {})
            assistant_config = configurable.get("assistant_config", {})
            
            table_name = assistant_config.get("table_name", "")
            config_columns = assistant_config.get("table_columns", [])
            max_distinct_values = assistant_config.get("max_distinct_values", business_config.get_max_distinct_values())
            
            if not table_name or not config_columns:
                error_msg = "Table name or columns not found in config"
                state["errors"] = {"error_message": error_msg}
                return state
            
            # Use table data extraction tool
            tool_result = table_data_extraction_tool.invoke({
                "table_name": table_name,
                "table_columns": config_columns,
                "max_distinct_values": max_distinct_values,
                "db_connection": self.db
            })
            
            state["table_info"] = tool_result
            
            columns = tool_result.get("columns", [])
            searchable_columns = [col["name"] for col in columns if col.get("distinct_values")]
            
            success_msg = f"""Tablo şeması başarıyla çekildi:

• **Tablo:** {table_name}
• **Kolonlar:** {len(columns)} adet
• **Aranabilir Kolonlar:** {len(searchable_columns)} adet

**Distinct değerler çekilen kolonlar:**
{', '.join(searchable_columns)}"""
            
            state["extraction_result"] = success_msg
            state["messages"].append(AIMessage(content=success_msg))
            
            # Store agent results
            if "agent_results" not in state:
                state["agent_results"] = {}
            state["agent_results"]["table_data_agent"] = {
                "status": "success",
                "data": tool_result,
                "message": success_msg
            }
            
            self.logger.info("Table Data Agent completed successfully", 
                           table=table_name, 
                           columns=len(columns),
                           searchable=len(searchable_columns))
            return state
            
        except Exception as e:
            error_msg = f"Table Data Agent failed: {str(e)}"
            state["errors"] = {"error_message": error_msg}
            state["extraction_result"] = error_msg
            state["messages"].append(AIMessage(content=error_msg))
            
            if "agent_results" not in state:
                state["agent_results"] = {}
            state["agent_results"]["table_data_agent"] = {
                "status": "error",
                "error": str(e),
                "message": error_msg
            }
            
            self.logger.error("Table Data Agent failed", error=str(e))
            return state


class ContextAnalysisAgent:
    """Specialized Agent for conversation context analysis"""
    
    def __init__(self, logger):
        self.logger = logger
        
    def execute(self, state: EnhancedText2SQLState, *, config) -> EnhancedText2SQLState:
        """Execute context analysis workflow"""
        state["current_agent"] = "context_analysis_agent"
        
        try:
            messages = state.get("messages", [])
            
            if not messages:
                error_msg = "No messages found for context analysis"
                state["errors"] = {"error_message": error_msg}
                return state
            
            # Filter only user messages for analysis
            user_messages = [msg for msg in messages if hasattr(msg, 'type') and msg.type == 'human']
            
            if not user_messages:
                error_msg = "No user messages found for context analysis"
                state["errors"] = {"error_message": error_msg}
                return state
            
            # Use context analysis tool with user messages only
            context_data = context_analysis_tool.invoke({
                "messages": user_messages,
                "max_tokens": 1500
            })
            
            state["context_analysis"] = context_data
            
            context_msg = f"""Context Analysis tamamlandı:

• **Mevcut Mesaj:** {context_data['current_message'][:100]}...
• **Context Mesajları:** {len(context_data['recent_context'])} adet
• **Token Kullanımı:** {context_data['total_tokens']}
• **Flow Indicators:** {len(context_data['flow_indicators']['pronoun_references']) + len(context_data['flow_indicators']['flow_words'])} adet"""
            
            state["messages"].append(AIMessage(content=context_msg))
            
            # Store agent results
            if "agent_results" not in state:
                state["agent_results"] = {}
            state["agent_results"]["context_analysis_agent"] = {
                "status": "success",
                "data": context_data,
                "message": context_msg
            }
            
            self.logger.info("Context Analysis Agent completed successfully",
                           tokens=context_data.get("total_tokens", 0))
            return state
            
        except Exception as e:
            error_msg = f"Context Analysis Agent failed: {str(e)}"
            state["errors"] = {"error_message": error_msg}
            state["messages"].append(AIMessage(content=error_msg))
            
            if "agent_results" not in state:
                state["agent_results"] = {}
            state["agent_results"]["context_analysis_agent"] = {
                "status": "error",
                "error": str(e),
                "message": error_msg
            }
            
            self.logger.error("Context Analysis Agent failed", error=str(e))
            return state


class IntentAnalysisAgent:
    """Specialized Agent for intent analysis using LLM with enhanced prompts"""
    
    def __init__(self, llm, logger):
        self.llm = llm
        self.logger = logger
        
    def execute(self, state: EnhancedText2SQLState, *, config) -> EnhancedText2SQLState:
        """Execute intent analysis workflow"""
        state["current_agent"] = "intent_analysis_agent"
        
        try:
            context_data = state.get("context_analysis", {})
            table_info = state.get("table_info", {})
            
            if not context_data:
                error_msg = "Context analysis data not found"
                state["errors"] = {"error_message": error_msg}
                return state
            
            start_time = time.time()
            
            # Use prompt builder tool
            enhanced_prompt = prompt_builder_tool.invoke({
                "context_data": context_data,
                "table_info": table_info
            })
            
            # LLM call for intent analysis
            response = self.llm.get_chat().invoke([{"role": "user", "content": enhanced_prompt}])
            
            # Use response parser tool
            analysis_result = response_parser_tool.invoke({
                "llm_response": response.content,
                "context_data": context_data
            })
            
            # Add performance metrics
            duration = time.time() - start_time
            analysis_result["performance"] = {
                "duration": f"{duration:.2f}s",
                "context_messages": len(context_data.get("recent_context", [])),
                "total_tokens": context_data.get("total_tokens", 0)
            }
            
            state["intent_analysis"] = analysis_result
            
            success_msg = self._format_analysis_result(analysis_result, context_data)
            state["analysis_result"] = success_msg
            state["messages"].append(AIMessage(content=success_msg))
            
            # Store agent results
            if "agent_results" not in state:
                state["agent_results"] = {}
            state["agent_results"]["intent_analysis_agent"] = {
                "status": "success",
                "data": analysis_result,
                "message": success_msg,
                "performance": analysis_result["performance"]
            }
            
            self.logger.info("Intent Analysis Agent completed successfully", 
                           duration=f"{duration:.2f}s",
                           confidence=f"{analysis_result['confidence']:.2f}",
                           intent=analysis_result["intent_type"])
            return state
            
        except Exception as e:
            error_msg = f"Intent Analysis Agent failed: {str(e)}"
            state["errors"] = {"error_message": error_msg}
            state["analysis_result"] = error_msg
            state["messages"].append(AIMessage(content=error_msg))
            
            if "agent_results" not in state:
                state["agent_results"] = {}
            state["agent_results"]["intent_analysis_agent"] = {
                "status": "error",
                "error": str(e),
                "message": error_msg
            }
            
            self.logger.error("Intent Analysis Agent failed", error=str(e))
            return state
    
    def _format_analysis_result(self, analysis_result: Dict, context_data: Dict) -> str:
        """Format analysis result for display"""
        return f"""Enhanced Intent Analizi Tamamlandı:

• **Intent Türü:** {analysis_result.get('intent_type', 'N/A')}
• **Konuşma Türü:** {analysis_result.get('conversation_type', 'N/A')}
• **Güven Skoru:** {analysis_result.get('confidence', 0):.2f}
• **Hedef Aksiyon:** {analysis_result.get('target_action', 'N/A')}
• **Context Gerekli:** {'Evet' if analysis_result.get('requires_context') else 'Hayır'}

**Analiz Gerekçesi:** {analysis_result.get('reasoning', 'N/A')}

**Context Referansları:** {', '.join(analysis_result.get('context_references', []))}
**Önerilen Entity'ler:** {', '.join(analysis_result.get('suggested_entities', []))}

**Token Kullanımı:** {context_data.get('total_tokens', 0)}"""


class SQLParameterExtractionAgent:
    """Specialized Agent for extracting SQL parameters from intent analysis"""
    
    def __init__(self, llm, logger):
        self.llm = llm
        self.logger = logger
        self._match_results = {}
        
    def execute(self, state: EnhancedText2SQLState, *, config) -> EnhancedText2SQLState:
        """Execute SQL parameter extraction workflow using intent analysis"""
        state["current_agent"] = "sql_parameter_extraction_agent"
        
        # Reset match results for new query to ensure consistent behavior
        self._match_results = {}
        
        try:
            # Get required data from state
            intent_analysis = state.get("intent_analysis", {})
            context_analysis = state.get("context_analysis", {})
            table_info = state.get("table_info", {})
            
            if not intent_analysis:
                error_msg = "Intent analysis not found for parameter extraction"
                state["errors"] = {"error_message": error_msg}
                return state
            
            # Store required data for parameter enhancement
            self._current_intent = intent_analysis
            self._current_table_info = table_info
            # Store LLM reference for distinct value matching
            self.llm = self.llm  # Ensure it's accessible
            
            # Get original user query
            user_query = ""
            for msg in reversed(state.get("messages", [])):  # Get the latest human message
                if hasattr(msg, 'content') and isinstance(msg, HumanMessage):
                    msg_content = msg.content
                    if isinstance(msg_content, list):
                        msg_content = ' '.join(str(item.get('text', str(item)) if isinstance(item, dict) else str(item)) for item in msg_content)
                    user_query = str(msg_content)
                    break
            
            # Store user query for multi-condition enhancement
            self._current_user_query = user_query
            
            # Build parameter extraction prompt
            extraction_prompt = self._build_parameter_extraction_prompt(
                user_query, intent_analysis, context_analysis
            )
            
            # Extract parameters using LLM
            response = self.llm.get_chat().invoke([{"role": "user", "content": extraction_prompt}])
            
            # Parse extracted parameters
            sql_parameters = self._parse_parameter_response(response.content, state)
            
            # Store parameters in state
            state["sql_parameters"] = sql_parameters
            
            success_msg = self._format_parameter_result(sql_parameters)
            state["messages"].append(AIMessage(content=success_msg))
            
            # Update state with distinct value matches for SQL generation
            if hasattr(self, '_match_results') and self._match_results:
                state["distinct_value_matches"] = self._match_results
                self.logger.info("Updated state with distinct value matches",
                               matches=self._match_results)
            
            # Store agent results
            if "agent_results" not in state:
                state["agent_results"] = {}
            state["agent_results"]["sql_parameter_extraction_agent"] = {
                "status": "success",
                "data": sql_parameters,
                "message": success_msg
            }
            
            self.logger.info("SQL Parameter Extraction Agent completed successfully", 
                           parameters_extracted=len(sql_parameters))
            return state
            
        except Exception as e:
            error_msg = f"SQL Parameter Extraction Agent failed: {str(e)}"
            state["errors"] = {"error_message": error_msg}
            state["messages"].append(AIMessage(content=error_msg))
            
            if "agent_results" not in state:
                state["agent_results"] = {}
            state["agent_results"]["sql_parameter_extraction_agent"] = {
                "status": "error",
                "error": str(e),
                "message": error_msg
            }
            
            self.logger.error("SQL Parameter Extraction Agent failed", error=str(e))
            return state
    
    def _build_parameter_extraction_prompt(self, user_query: str, intent_analysis: Dict, context_analysis: Dict) -> str:
        """Build parameter extraction prompt based on intent analysis"""
        
        intent_type = intent_analysis.get('intent_type', 'list')
        suggested_entities = intent_analysis.get('suggested_entities', [])
        target_action = intent_analysis.get('target_action', '')
        
        # Extract more entities from user query for better matching
        if isinstance(user_query, list):
            user_query = ' '.join(str(item) for item in user_query)
        user_query_upper = str(user_query).upper()
        additional_entities = []
        
        # Common Turkish business terms that might be column names
        business_terms = [
            'BELGETURU', 'BELGETIPI', 'CARI', 'CARIKODU', 'CARIAD', 'CARIUNVAN',
            'TUTAR', 'NETTUTAR', 'NETTUTARDAHIL', 'TOPLAM', 'MIKTAR', 'BIRIMFIYAT',
            'TARIH', 'BELGENO', 'SERI', 'SIRA', 'ACIKLAMA', 'DEPARTMAN',
            'PERSONEL', 'URUN', 'STOK', 'KDV', 'KDVTUTAR', 'KDVOران', 'VERGI', 'ISKONTO'
        ]
        
        # Intent-based entity mapping
        intent_mappings = {
            'kdv': ['KDVTUTAR', 'KDV', 'KDVORANA', 'KDVMATRAH', 'KDVISKONTO'],
            'istisna': ['KDVTUTAR', 'KDVISKONTO', 'OTIVTUTAR'],
            'tutar': ['TUTAR', 'KDVTUTAR', 'NETTUTAR', 'TOPLAM', 'GERÇEKTOPLAM'],
            'cari': ['CARIKODU', 'CARIAD', 'CARIUNVAN', 'CARIGRUBU', 'CARITUR', 'CARISINIF'],
            'grup': ['CARIGRUBU', 'CARIKODU', 'CARIAD', 'CARIUNVAN']
        }
        
        # Extract potential entities from user query
        words = user_query_upper.split()
        for word in words:
            word_clean = word.strip('.,!?()[]{}')
            if len(word_clean) > 2:
                # Add if it's a business term or looks like a column name
                if word_clean in business_terms or word_clean.isupper():
                    additional_entities.append(word_clean)
        
        # Intent-based entity extraction
        intent_entities = []
        user_query_lower = user_query.lower()
        
        for key, values in intent_mappings.items():
            if key in user_query_lower:
                intent_entities.extend(values)
        
        # Special handling for "kdv istisna tutarı"
        if 'kdv' in user_query_lower and ('istisna' in user_query_lower or 'tutar' in user_query_lower):
            intent_entities.extend(['KDVTUTAR', 'KDVISKONTO'])
        
        # Special handling for "carilere göre gruplayarak"
        if ('cari' in user_query_lower or 'carilere' in user_query_lower) and 'grup' in user_query_lower:
            intent_entities.extend(['CARIKODU', 'CARIAD', 'CARIUNVAN'])
        
        # Enhanced multi-condition extraction
        # Check for multiple AND conditions in user query
        if ' ve ' in user_query_lower or ' and ' in user_query_lower:
            # Extract conditions before and after "ve/and"
            condition_parts = user_query_lower.replace(' and ', ' ve ').split(' ve ')
            for part in condition_parts:
                part = part.strip()
                
                # Extract entity-value pairs from each part
                if 'cari' in part and any(val in part for val in ['doğalgaz', 'dogalgaz']):
                    intent_entities.extend(['CARIKODU', 'CARIAD'])
                if 'belge' in part and 'tip' in part:
                    intent_entities.extend(['BELGETIPI', 'BELGETURU'])
                if 'stok' in part and 'giriş' in part:
                    intent_entities.extend(['BELGETIPI'])
                if 'fatura' in part:
                    intent_entities.extend(['BELGETIPI', 'BELGENO'])
        
        # Combine and deduplicate entities
        all_entities = list(set(suggested_entities + additional_entities + intent_entities))
        
        return f"""SQL PARAMETER EXTRACTION TASK

KULLANICI SORGUSU: "{user_query}"

INTENT ANALİZİ:
- Intent Türü: {intent_type}
- Hedef Aksiyon: {target_action}
- Tespit Edilen Entity'ler: {', '.join(all_entities)}

GÖREV: Kullanıcının sorgusundan SQL parametrelerini çıkar ve aşağıdaki kategorilere ayır:

SQL RAPORLAMA İFADELERİ:

1. TEMEL SORGULAMA:
   - SELECT: Hangi kolonlar getirilecek (*, belirli kolonlar)
   - FROM: Hangi tablo
   - WHERE: Filtreleme koşulları
   - DISTINCT: Tekrarsız kayıtlar (true/false)
   - TOP/LIMIT: Kayıt sayısı sınırı

2. GRUPLAMA VE SIRALAMA:
   - GROUP BY: Gruplama kolonları
   - HAVING: Gruplar için filtreleme
   - ORDER BY: Sıralama (ASC/DESC)

3. BİRLEŞTİRME:
   - JOIN türleri: INNER, LEFT, RIGHT, FULL OUTER
   - UNION: Sonuçları birleştir

4. TOPLAM FONKSİYONLARI:
   - COUNT, SUM, AVG, MIN, MAX

5. WHERE KOŞUL OPERATÖRLERİ:
   - Karşılaştırma: =, !=, >, <, >=, <=
   - Aralık: BETWEEN, NOT BETWEEN
   - Liste: IN, NOT IN
   - Metin: LIKE, NOT LIKE
   - NULL: IS NULL, IS NOT NULL
   - Mantıksal: AND, OR, NOT

ÖNEMLİ: Kullanıcı "ve" kelimesi kullanıyorsa multiple WHERE conditions oluştur:
- "cari kodu X olan ve belge tipi Y olan" → 2 ayrı WHERE condition
- Her condition için ayrı column, operator, value, logical

ÇOK ÖNEMLİ - DISTINCT VALUE MATCHING:
- Kullanıcının girdiği değerleri tablodaki gerçek distinct değerlerle eşleştir
- Örnek: "dogalgaz" → "Baskent Dogalgaz Dagitim Gayrimenkul Yatirim Ortakligi Anonim Sirketi"
- Semantic matching kullan, exact match gerekli değil
- ZORUNLU: Sadece tablodaki mevcut değerleri kullan

SIRALAMA VE LIMIT:
- "tersten sırala", "ters sırala" → ORDER BY DESC  
- "ilk X kayıt", "sadece X kayıt" → TOP X limit
- Belge no, tarih, tutar gibi kolonlara göre sıralama

6. GELİŞMİŞ:
   - CASE WHEN: Koşullu ifade
   - EXISTS/NOT EXISTS: Alt sorgu varlık kontrolü
   - SUBQUERY: Alt sorgu
   - WITH (CTE): Geçici sonuç kümesi

7. PENCERE FONKSİYONLARI:
   - ROW_NUMBER(), RANK(), DENSE_RANK()
   - PARTITION BY, OVER

8. TARİH/ZAMAN:
   - DATEPART, DATEDIFF, GETDATE()/NOW()

ÇIKTI FORMATI (JSON):
{{
    "select_columns": ["kolon1", "kolon2"] veya ["*"],
    "from_table": "tablo_adi",
    "where_conditions": [
        {{
            "column": "kolon_adi",
            "operator": "=|!=|>|<|>=|<=|LIKE|IN|BETWEEN|IS NULL",
            "value": "deger",
            "logical": "AND|OR"
        }}
    ],
    "distinct": true/false,
    "top_limit": sayı veya null,
    "group_by": ["kolon1", "kolon2"],
    "having_conditions": [],
    "order_by": [
        {{
            "column": "kolon_adi",
            "direction": "ASC|DESC"
        }}
    ],
    "aggregate_functions": [
        {{
            "function": "COUNT|SUM|AVG|MIN|MAX",
            "column": "kolon_adi",
            "alias": "takma_ad"
        }}
    ],
    "joins": [
        {{
            "type": "INNER|LEFT|RIGHT|FULL OUTER",
            "table": "tablo_adi",
            "condition": "join_kosulu"
        }}
    ],
    "case_when": [],
    "subqueries": [],
    "window_functions": [],
    "date_functions": []
}}

DİKKAT: Entity'leri kolon adlarıyla eşleştirirken esnek ol. Örneğin:
- 'BELGETURU' ve 'BELGETIPI' benzer anlamda
- 'NETTUTAR' ve 'NETTUTARDAHIL' benzer anlamda
- 'CARI' kelimesi 'CARIKODU' veya 'CARIUNVAN' olabilir

KULLANICI SORGUSUNU ANALİZ ET VE PARAMETRELERI ÇIKAR:"""

    def _parse_parameter_response(self, response_content: str, state: EnhancedText2SQLState) -> Dict:
        """Parse SQL parameters from LLM response"""
        try:
            import json
            import re
            
            # Try to extract JSON from response with better patterns
            json_patterns = [
                r'```json\s*(\{.*?\})\s*```',  # Code blocks
                r'```\s*(\{.*?\})\s*```',      # Generic code blocks
                r'(\{[\s\S]*?\})'              # Any JSON-like structure
            ]
            
            parameters = None
            for pattern in json_patterns:
                json_match = re.search(pattern, response_content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                    try:
                        # Try to fix common JSON issues
                        json_str = self._fix_json_format(json_str)
                        parameters = json.loads(json_str)
                        break
                    except json.JSONDecodeError as je:
                        self.logger.debug(f"JSON decode failed for pattern {pattern}", 
                                        json_str=json_str[:200], error=str(je))
                        continue
            
            if not parameters:
                self.logger.warning("Could not parse any JSON from LLM response", 
                                  response_preview=response_content[:300])
                return self._create_default_parameters()
            
            if parameters:
                
                # Validate and set defaults
                default_parameters = {
                    "select_columns": ["*"],
                    "from_table": "",
                    "where_conditions": [],
                    "distinct": False,
                    "top_limit": None,
                    "group_by": [],
                    "having_conditions": [],
                    "order_by": [],
                    "aggregate_functions": [],
                    "joins": [],
                    "case_when": [],
                    "subqueries": [],
                    "window_functions": [],
                    "date_functions": []
                }
                
                # Merge with defaults
                for key, default_value in default_parameters.items():
                    if key not in parameters:
                        parameters[key] = default_value
                
                        # Enhanced multi-condition parsing for user queries with logical operators
                user_query = getattr(self, '_current_user_query', '')
                if user_query and self._has_complex_logical_conditions(user_query):
                    parameters = self._enhance_multi_condition_parameters(parameters, user_query, state)
                    # Add parentheses grouping for complex conditions
                    parameters = self._add_logical_grouping(parameters, user_query)
                
                # Extract ORDER BY and TOP from user query
                if user_query:
                    parameters = self._extract_order_by_and_top(parameters, user_query)
                
                # Intent-based automatic parameter enhancement
                self._enhance_parameters_by_intent(parameters)
                
                # Distinct value matching using LLM tool
                self._perform_distinct_value_matching(parameters, state)
                
                # Store distinct value match results in state for SQL generation
                if hasattr(self, '_match_results') and self._match_results:
                    parameters['distinct_value_matches'] = self._match_results
                    self.logger.info("Added distinct value matches to parameters", 
                                   match_count=len(self._match_results))
                
                # CRITICAL: Validate extracted parameters and add fallback conditions
                parameters = self._validate_and_enhance_parameters(parameters, user_query, state)
                
                return parameters
            else:
                return self._create_default_parameters()
                
        except json.JSONDecodeError as je:
            self.logger.error("JSON decode error in parameter parsing", 
                            error=str(je), response_preview=response_content[:300])
            return self._create_default_parameters()
        except Exception as e:
            self.logger.error("Unexpected error in parameter parsing", 
                            error=str(e), response_preview=response_content[:300])
            return self._create_default_parameters()
    
    def _enhance_multi_condition_parameters(self, parameters: Dict, user_query: str, state: EnhancedText2SQLState) -> Dict:
        """Enhance parameters for complex multi-condition queries with nested and/or logic"""
        try:
            user_query_lower = user_query.lower()
            
            # Enhanced logical operator detection
            logical_patterns = {
                'and': ['ve', 'and', 'ile', 'beraber', 'aynı zamanda'],
                'or': ['veya', 'or', 'ya da', 'yada', 'yoksa', 'alternatif olarak']
            }
            
            # Parse complex nested conditions
            enhanced_conditions = self._parse_complex_logical_conditions(user_query_lower, logical_patterns, state)
            
            if enhanced_conditions:
                # Deduplicate conditions by column and value
                deduplicated_conditions = []
                seen_conditions = set()
                
                for condition in enhanced_conditions:
                    column = condition.get('column', '')
                    value = condition.get('value', '')
                    condition_key = f"{column}:{value}"
                    
                    if condition_key not in seen_conditions:
                        deduplicated_conditions.append(condition)
                        seen_conditions.add(condition_key)
                    else:
                        self.logger.warning("Duplicate condition detected and removed", 
                                          column=column, value=value)
                
                # Replace existing conditions with deduplicated ones
                parameters['where_conditions'] = deduplicated_conditions
                
                self.logger.info("Enhanced multi-condition parameters", 
                               total_conditions=len(parameters['where_conditions']),
                               new_conditions=len(enhanced_conditions))
            
            return parameters
            
        except Exception as e:
            self.logger.error("Failed to enhance multi-condition parameters", error=str(e))
            return parameters

    def _parse_complex_logical_conditions(self, query: str, logical_patterns: Dict, state: EnhancedText2SQLState) -> List[Dict]:
        """Parse complex nested logical conditions from user query"""
        conditions = []
        
        try:
            # Handle parentheses for nested logic
            query = self._normalize_query_for_parsing(query)
            
            # Split by main logical operators
            condition_blocks = self._split_by_logical_operators(query, logical_patterns)
            
            for i, (block, logical_op) in enumerate(condition_blocks):
                block_conditions = self._extract_conditions_from_block(block.strip(), state)
                
                # Apply logical operator to conditions from this block
                for j, condition in enumerate(block_conditions):
                    # First condition of first block has no logical operator
                    if i == 0 and j == 0:
                        condition['logical'] = ''
                    # First condition of subsequent blocks uses the block's logical operator
                    elif j == 0:
                        condition['logical'] = logical_op
                    # Subsequent conditions within a block use AND (default for same block)
                    else:
                        condition['logical'] = 'AND'
                    
                    conditions.append(condition)
            
        except Exception as e:
            self.logger.error("Failed to parse complex logical conditions", error=str(e))
            
        return conditions
    
    def _normalize_query_for_parsing(self, query: str) -> str:
        """Normalize query for better parsing"""
        # Replace common variations
        query = query.replace(' and ', ' ve ')
        query = query.replace(' ya da ', ' veya ')
        query = query.replace(' yada ', ' veya ')
        
        # Normalize whitespace around operators
        import re
        query = re.sub(r'\s+(ve|veya|and|or)\s+', r' \1 ', query)
        
        return query
    
    def _split_by_logical_operators(self, query: str, logical_patterns: Dict) -> List[tuple]:
        """Split query by logical operators while preserving operator information"""
        import re
        
        # Create pattern for all logical operators
        all_operators = []
        for op_type, variants in logical_patterns.items():
            all_operators.extend(variants)
        
        # Create regex pattern
        pattern = r'\s+(' + '|'.join(re.escape(op) for op in all_operators) + r')\s+'
        
        # Split while keeping delimiters
        parts = re.split(pattern, query, flags=re.IGNORECASE)
        
        # Group parts with their logical operators
        blocks = []
        current_block = parts[0] if parts else ''
        
        i = 1
        while i < len(parts):
            if i + 1 < len(parts):
                operator = parts[i].strip().lower()
                next_block = parts[i + 1]
                
                # Determine operator type
                op_type = 'AND'  # default
                for logic_type, variants in logical_patterns.items():
                    if operator in variants:
                        op_type = logic_type.upper()
                        break
                
                blocks.append((current_block, ''))  # First block has no operator
                current_block = next_block
                
                # Store operator for next block
                if i + 2 < len(parts):
                    i += 2
                else:
                    blocks.append((current_block, op_type))
                    break
            else:
                i += 1
        
        if current_block and not any(current_block in block[0] for block in blocks):
            blocks.append((current_block, ''))
        
        return blocks if blocks else [(query, '')]
    
    def _extract_conditions_from_block(self, block: str, state: EnhancedText2SQLState) -> List[Dict]:
        """Extract individual conditions from a text block"""
        conditions = []
        
        # Get table info for distinct value matching
        table_info = state.get('table_info', {})
        columns = table_info.get('columns', [])
        
        # Enhanced condition patterns with more flexible matching
        condition_patterns = [
            # Cari patterns - more specific matching with explicit operators
            {
                'pattern': r'cari\s*kodu?\s*([a-zA-ZÜĞIŞÇÖüğışçö0-9\s]+?)\s*olan',
                'column_mapping': {},
                'default_column': 'CariKodu',
                'operator': '='
            },
            {
                'pattern': r'cari\s*ad[ıi]?\s*([a-zA-ZÜĞIŞÇÖüğışçö0-9\s]+?)\s*olan',
                'column_mapping': {},
                'default_column': 'CariAdi',
                'operator': '='
            },
            {
                'pattern': r'cari\s*unvan[ı]?\s*([a-zA-ZÜĞIŞÇÖüğışçö0-9\s]+?)\s*olan',
                'column_mapping': {},
                'default_column': 'CariUnvan',
                'operator': '='
            },
            # Belge tipi patterns
            {
                'pattern': r'belge\s*tip[i]?\s*([a-zA-ZÜĞIŞÇÖüğışçö\s]+?)\s*olan',
                'column_mapping': {},
                'default_column': 'BelgeTipi',
                'operator': '='
            },
            # Tutar patterns with operator detection
            {
                'pattern': r'tutar[ı]?\s*([0-9.,]+)\s*(?:üzer[i]|yukar[ı]|fazla)',
                'column_mapping': {},
                'default_column': 'NetTutar',
                'operator': '>'
            },
            {
                'pattern': r'tutar[ı]?\s*([0-9.,]+)\s*(?:alt[ıi]|aşağ[ı]|az)',
                'column_mapping': {},
                'default_column': 'NetTutar', 
                'operator': '<'
            },
            {
                'pattern': r'kdv\s*(?:si|tutar[ı]?|oranı)?\s*([0-9.,]+)\s*(?:üzer[i]|yukar[ı]|fazla)',
                'column_mapping': {},
                'default_column': 'KDVTutar',
                'operator': '>'
            },
            {
                'pattern': r'kdv\s*(?:si|tutar[ı]?|oranı)?\s*([0-9.,]+)\s*(?:alt[ıi]|aşağ[ı]|az)',
                'column_mapping': {},
                'default_column': 'KDVTutar',
                'operator': '<'
            },
            # Date patterns - specific patterns first, then general
            {
                'pattern': r'tarih[i]?\s*([0-9]{4})\s*(ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)\s*(?:ayında|ayı)',
                'column_mapping': {},
                'default_column': None,  # Dynamic selection
                'operator': 'LIKE',
                'requires_dynamic_column_selection': True,
                'value_type': 'date',
                'value_formatter': lambda x: self._format_year_month_dynamic(x, columns)
            },
            {
                'pattern': r'tarih[i]?\s*([0-9]{4})\s*(?:yılında|yılı|year)',
                'column_mapping': {},
                'default_column': 'BelgeTarih',
                'operator': 'LIKE',
                'value_formatter': lambda x: f"'{x}%'"
            },
            {
                'pattern': r'tarih[i]?\s*([0-9]{1,2}[/.][0-9]{1,2}[/.][0-9]{2,4})\s*(?:sonr[aı]s[ıi]|sonra)',
                'column_mapping': {},
                'default_column': 'BelgeTarih',
                'operator': '>'
            },
            {
                'pattern': r'tarih[i]?\s*([0-9]{1,2}[/.][0-9]{1,2}[/.][0-9]{2,4})\s*(?:önce[si]|evvel)',
                'column_mapping': {},
                'default_column': 'BelgeTarih',
                'operator': '<'
            },
            {
                'pattern': r'tarih[i]?\s*([0-9]{1,2}[/.][0-9]{1,2}[/.][0-9]{2,4})\s*(?:olan|eşit)',
                'column_mapping': {},
                'default_column': 'BelgeTarih',
                'operator': '='
            },
            # MM/YYYY pattern for month-year searches (dynamic column selection)
            {
                'pattern': r'(?:tarih[i]?.*?)?([0-9]{1,2}[/.][0-9]{4})',
                'column_mapping': {},
                'default_column': None,  # Will be dynamically chosen
                'operator': 'LIKE',
                'value_formatter': lambda x: self._format_dynamic_value(x, columns, 'date'),
                'requires_dynamic_column_selection': True,
                'value_type': 'date'
            }
        ]
        
        import re
        
        for pattern_info in condition_patterns:
            pattern = pattern_info['pattern']
            matches = re.finditer(pattern, block, re.IGNORECASE)
            
            for match in matches:
                groups = match.groups()
                if len(groups) >= 1:
                    # Use dynamic column selection if required
                    if pattern_info.get('requires_dynamic_column_selection', False):
                        # For dynamic patterns, use the value_formatter first to get proper input for column selection
                        if 'value_formatter' in pattern_info:
                            if len(groups) >= 2:
                                formatted_value = pattern_info['value_formatter'](groups)
                            else:
                                formatted_value = pattern_info['value_formatter'](groups[0].strip())
                            # Get the column selected by the dynamic formatter
                            column = getattr(self, '_temp_dynamic_column', {}).get('selected', 'BelgeTarih')
                        else:
                            value = groups[0].strip()
                            column_and_value = self._select_dynamic_column_and_format(
                                value, columns, pattern_info.get('value_type', 'text')
                            )
                            column = column_and_value['column']
                            formatted_value = column_and_value['formatted_value']
                    else:
                        column = pattern_info['default_column']
                        value = groups[0].strip()
                    
                    # Use pattern-specific operator or determine from context
                    if 'operator' in pattern_info:
                        operator = pattern_info['operator']
                    else:
                        operator = self._determine_operator(block, match.group())
                    
                    # Handle value formatting based on pattern type
                    if pattern_info.get('requires_dynamic_column_selection', False):
                        # Dynamic selection already handled formatting, use as-is
                        pass  # formatted_value already set above
                    elif 'value_formatter' in pattern_info:
                        # For complex patterns like "2025 temmuz" 
                        value = value.replace("'", "").strip()  # Clean up first
                        if len(groups) >= 2:
                            formatted_value = pattern_info['value_formatter'](groups)
                        else:
                            formatted_value = pattern_info['value_formatter'](value)
                    else:
                        # Standard processing: clean value and match with distinct values
                        value = value.replace("'", "").strip()
                        matched_value = self._match_with_distinct_values(value, column, columns)
                        
                        # Format value for SQL
                        if matched_value.replace('.', '').replace(',', '').isdigit():
                            formatted_value = matched_value  # Keep numbers as-is
                        else:
                            formatted_value = f"'{matched_value}'"  # Quote strings
                    
                    condition = {
                        'column': column,
                        'operator': operator,
                        'value': formatted_value,
                        'logical': ''  # Will be set by caller
                    }
                    
                    conditions.append(condition)
        
        return conditions
    
    def _map_column_name(self, potential_column: str) -> str:
        """Map potential column name to actual database column"""
        column_mapping = {
            'cari': 'CariKodu', 'carikodu': 'CariKodu', 'cari_kodu': 'CariKodu',
            'cariad': 'CariAdi', 'cari_adi': 'CariAdi', 'cariunvan': 'CariUnvan',
            'belge': 'BelgeTipi', 'belgetipi': 'BelgeTipi', 'belgeturu': 'BelgeTipi',
            'tutar': 'NetTutar', 'nettutar': 'NetTutar', 'kdvtutar': 'KDVTutar',
            'tarih': 'Tarih', 'belgeno': 'BelgeNo', 'seri': 'Seri', 'sira': 'Sira'
        }
        
        return column_mapping.get(potential_column.lower(), potential_column)
    
    def _determine_operator(self, context: str, match_text: str) -> str:
        """Determine the appropriate SQL operator based on context"""
        context_lower = context.lower()
        match_lower = match_text.lower()
        
        # Check for comparison operators in context
        if any(word in context_lower for word in ['üzer', 'büyük', 'fazla', 'yüksek']) or any(word in match_lower for word in ['üzer', 'fazla']):
            return '>'
        elif any(word in context_lower for word in ['alt', 'küçük', 'az', 'düşük']) or any(word in match_lower for word in ['alt', 'az']):
            return '<'
        elif any(word in context_lower for word in ['eşit', 'equal']):
            return '='
        elif any(word in context_lower for word in ['değil', 'hariç', 'except']):
            return '!='
        elif any(word in context_lower for word in ['içer', 'benzer', 'like']):
            return 'LIKE'
        elif any(word in context_lower for word in ['aras', 'between']):
            return 'BETWEEN'
        # For text values that should be equality matches (names, types, etc.)
        elif any(word in match_lower for word in ['cari', 'ad', 'belge', 'tip']) and 'olan' in context_lower:
            return '='
        else:
            return '='  # Default to equality

    def _month_to_number(self, month_name: str) -> int:
        """Convert Turkish month name to number"""
        months = {
            'ocak': 1, 'şubat': 2, 'mart': 3, 'nisan': 4, 'mayıs': 5, 'haziran': 6,
            'temmuz': 7, 'ağustos': 8, 'eylül': 9, 'ekim': 10, 'kasım': 11, 'aralık': 12
        }
        return months.get(month_name.lower(), 1)

    def _select_dynamic_column_and_format(self, user_value: str, columns: List[Dict], value_type: str) -> Dict[str, str]:
        """Dynamically select the best column and format the value based on distinct values analysis"""
        try:
            # Analyze all columns to find the best match
            column_scores = []
            
            for col in columns:
                col_name = col.get('name', '')
                distinct_values = col.get('distinct_values', [])
                
                if not distinct_values:
                    continue
                
                # Calculate compatibility score for this column
                score = self._calculate_column_compatibility_score(user_value, distinct_values, value_type)
                if score > 0:
                    column_scores.append({
                        'column': col_name,
                        'score': score,
                        'distinct_values': distinct_values,
                        'best_format': self._determine_best_format(user_value, distinct_values, value_type)
                    })
            
            if not column_scores:
                # No compatible columns found, use fallback
                return {
                    'column': self._get_fallback_column(value_type),
                    'formatted_value': f"'%{user_value}%'"
                }
            
            # Select the column with highest score
            best_match = max(column_scores, key=lambda x: x['score'])
            
            self.logger.info("Dynamic column selection completed", 
                           selected_column=best_match['column'],
                           score=best_match['score'],
                           user_value=user_value,
                           format=best_match['best_format'])
            
            return {
                'column': best_match['column'],
                'formatted_value': best_match['best_format']
            }
            
        except Exception as e:
            self.logger.error("Dynamic column selection failed", error=str(e), user_value=user_value)
            return {
                'column': self._get_fallback_column(value_type),
                'formatted_value': f"'%{user_value}%'"
            }
    
    def _calculate_column_compatibility_score(self, user_value: str, distinct_values: List, value_type: str) -> float:
        """Calculate how compatible a user value is with a column's distinct values"""
        if not distinct_values:
            return 0.0
            
        scores = []
        
        for distinct_val in distinct_values[:50]:  # Limit analysis to first 50 values
            if distinct_val is None:
                continue
                
            str_distinct = str(distinct_val)
            similarity = self._calculate_value_similarity(user_value, str_distinct, value_type)
            scores.append(similarity)
        
        if not scores:
            return 0.0
            
        # Return the maximum similarity score
        max_score = max(scores)
        
        # Boost score if we have multiple good matches
        good_matches = len([s for s in scores if s > 0.5])
        if good_matches > 1:
            max_score += 0.1 * min(good_matches, 5)  # Cap the bonus
            
        return min(max_score, 1.0)  # Cap at 1.0
    
    def _calculate_value_similarity(self, user_value: str, distinct_value: str, value_type: str) -> float:
        """Calculate similarity between user input and distinct value"""
        user_lower = user_value.lower().strip()
        distinct_lower = distinct_value.lower().strip()
        
        # Exact match
        if user_lower == distinct_lower:
            return 1.0
            
        # For date type values
        if value_type == 'date':
            return self._calculate_date_similarity(user_value, distinct_value)
        
        # Substring matches
        if user_lower in distinct_lower:
            return 0.8
        if distinct_lower in user_lower:
            return 0.7
            
        # Partial word matches
        user_words = user_lower.split()
        distinct_words = distinct_lower.split()
        
        if user_words and distinct_words:
            word_matches = sum(1 for uw in user_words if any(uw in dw for dw in distinct_words))
            if word_matches > 0:
                return 0.6 * (word_matches / len(user_words))
        
        return 0.0
    
    def _calculate_date_similarity(self, user_value: str, distinct_value: str) -> float:
        """Calculate similarity specifically for date values"""
        import re
        
        # Check if user value is MM/YYYY format
        mm_yyyy_pattern = re.match(r'^(\d{1,2})/(\d{4})$', user_value.strip())
        if mm_yyyy_pattern:
            month, year = mm_yyyy_pattern.groups()
            month = month.zfill(2)
            
            # Check various date formats in distinct value
            distinct_str = str(distinct_value).strip()
            
            # MM/YYYY format match
            if f"{month}/{year}" in distinct_str:
                return 1.0
            
            # YYYY-MM format match
            if f"{year}-{month}" in distinct_str:
                return 0.95
            
            # Year-only match
            if year in distinct_str:
                return 0.7
                
            # Month-only match (less reliable)
            if month in distinct_str and len(distinct_str) <= 10:
                return 0.5
        
        return 0.0
    
    def _determine_best_format(self, user_value: str, distinct_values: List, value_type: str) -> str:
        """Determine the best format for the value based on distinct values patterns"""
        if value_type == 'date':
            return self._determine_date_format(user_value, distinct_values)
        
        # For non-date values, use standard LIKE format
        return f"'%{user_value}%'"
    
    def _determine_date_format(self, user_value: str, distinct_values: List) -> str:
        """Determine the best date format based on actual distinct values"""
        import re
        
        # Analyze the format patterns in distinct values
        format_scores = {'mm_yyyy': 0, 'yyyy_mm': 0, 'full_date': 0}
        
        for val in distinct_values[:20]:  # Analyze first 20 values
            if val is None:
                continue
                
            val_str = str(val).strip()
            
            # Count different format patterns
            if re.search(r'\d{2}/\d{4}', val_str):
                format_scores['mm_yyyy'] += 1
            if re.search(r'\d{4}-\d{2}', val_str):
                format_scores['yyyy_mm'] += 1
            if re.search(r'\d{4}-\d{2}-\d{2}', val_str):
                format_scores['full_date'] += 1
        
        # Parse user input
        mm_yyyy_match = re.match(r'^(\d{1,2})/(\d{4})$', user_value.strip())
        if mm_yyyy_match:
            month, year = mm_yyyy_match.groups()
            month = month.zfill(2)
            
            # CRITICAL FIX: Always prioritize YYYY-MM format for SQL compatibility
            # This fixes the 07/2025 -> %07/2025% vs %2025-07% issue
            if format_scores['yyyy_mm'] > 0 or format_scores['full_date'] > 0:
                return f"'%{year}-{month}%'"
            elif format_scores['mm_yyyy'] > 0:
                return f"'%{month}/{year}%'"
            else:
                # Default to SQL standard YYYY-MM format
                return f"'%{year}-{month}%'"
        
        # Fallback
        return f"'%{user_value}%'"
    
    def _get_fallback_column(self, value_type: str) -> str:
        """Get a fallback column name based on value type"""
        fallback_map = {
            'date': 'BelgeTarih',
            'text': 'CariAdi', 
            'numeric': 'NetTutar'
        }
        return fallback_map.get(value_type, 'BelgeTarih')
    
    def _format_dynamic_value(self, user_value: str, columns: List[Dict], value_type: str) -> str:
        """Dynamic value formatter - called from pattern lambda"""
        result = self._select_dynamic_column_and_format(user_value, columns, value_type)
        return result['formatted_value']

    def _format_year_month_dynamic(self, groups, columns: List[Dict]) -> Dict[str, str]:
        """Dynamic formatter for YYYY month_name patterns (e.g., '2025 temmuz')"""
        try:
            year = groups[0]
            month_name = groups[1]
            month_num = self._month_to_number(month_name)
            
            # Create MM/YYYY format for dynamic selection
            mm_yyyy_format = f"{month_num:02d}/{year}"
            
            # Use dynamic column selection
            result = self._select_dynamic_column_and_format(mm_yyyy_format, columns, 'date')
            
            # Store the selected column for the condition
            if not hasattr(self, '_temp_dynamic_column'):
                self._temp_dynamic_column = {}
            self._temp_dynamic_column['selected'] = result['column']
            
            return result['formatted_value']
            
        except Exception as e:
            # Fallback to old format
            year = groups[0] if groups else '2025'
            month_name = groups[1] if len(groups) > 1 else 'ocak'
            month_num = self._month_to_number(month_name)
            
            # Store fallback column
            if not hasattr(self, '_temp_dynamic_column'):
                self._temp_dynamic_column = {}
            self._temp_dynamic_column['selected'] = 'BelgeTarih'
            
            return f"'{year}-{month_num:02d}%'"

    def _validate_and_enhance_parameters(self, parameters: Dict, user_query: str, state: EnhancedText2SQLState) -> Dict:
        """Validate extracted parameters and enhance with fallback condition extraction if needed"""
        try:
            # Check if we have meaningful WHERE conditions
            where_conditions = parameters.get('where_conditions', [])
            has_valid_conditions = bool(where_conditions and len(where_conditions) > 0)
            
            self.logger.info("Parameter validation started", 
                           has_conditions=has_valid_conditions,
                           condition_count=len(where_conditions),
                           user_query_length=len(user_query))
            
            # If no conditions extracted but user query seems to have filter criteria, try fallback extraction
            if not has_valid_conditions and user_query and len(user_query) > 20:
                # Check if query contains filter keywords
                filter_indicators = ['olan', 'fazla', 'az', 'büyük', 'küçük', 'eşit', 'içeren', 'geçen', 'sonra', 'önce']
                has_filter_keywords = any(keyword in user_query.lower() for keyword in filter_indicators)
                
                if has_filter_keywords:
                    self.logger.warning("No conditions extracted but query seems to have filters - attempting fallback extraction",
                                      user_query=user_query[:100])
                    
                    # Try direct condition extraction as fallback
                    fallback_conditions = self._extract_conditions_from_block(user_query, state)
                    if fallback_conditions:
                        parameters['where_conditions'] = fallback_conditions
                        self.logger.info("Fallback condition extraction successful", 
                                       fallback_condition_count=len(fallback_conditions))
                    else:
                        self.logger.warning("Fallback condition extraction also failed")
            
            # Validate other critical parameters
            if not parameters.get('from_table'):
                # Try to get table name from state
                table_info = state.get('table_info', {})
                if table_info and 'name' in table_info:
                    parameters['from_table'] = table_info['name']
                    self.logger.info("Added missing table name from state", 
                                   table_name=parameters['from_table'])
            
            # Ensure select columns are not empty
            if not parameters.get('select_columns') or parameters['select_columns'] == []:
                parameters['select_columns'] = ['*']
                self.logger.info("Added default SELECT * due to empty select columns")
            
            # Validate ORDER BY and TOP extraction
            if user_query:
                # Check for ordering keywords
                if any(keyword in user_query.lower() for keyword in ['sırala', 'tersten', 'azalan', 'artan']):
                    if not parameters.get('order_by'):
                        # Try to extract ordering info
                        parameters = self._extract_order_by_and_top(parameters, user_query)
                
                # Check for limit keywords  
                if any(keyword in user_query.lower() for keyword in ['ilk', 'top', 'yalnızca', 'sadece']):
                    if not parameters.get('top_limit'):
                        # Try to extract top limit
                        import re
                        top_match = re.search(r'(?:ilk|top)\s*(\d+)', user_query.lower())
                        if top_match:
                            parameters['top_limit'] = int(top_match.group(1))
                            self.logger.info("Extracted TOP limit from query", top_limit=parameters['top_limit'])
            
            self.logger.info("Parameter validation completed", 
                           final_condition_count=len(parameters.get('where_conditions', [])),
                           has_table=bool(parameters.get('from_table')),
                           has_order=bool(parameters.get('order_by')),
                           has_limit=bool(parameters.get('top_limit')))
            
            return parameters
            
        except Exception as e:
            self.logger.error("Parameter validation failed", error=str(e), exc_info=True)
            # Return parameters as-is if validation fails
            return parameters

    def _store_match_info(self, column: str, match_info: dict) -> None:
        """Store match info for state update"""
        try:
            if not hasattr(self, '_match_results'):
                self._match_results = {}
            
            self._match_results[column] = match_info
            
            self.logger.info("Stored match info for state update", 
                           column=column, 
                           match_info=match_info)
        except Exception as e:
            self.logger.error("Failed to store match info", error=str(e))

    def _match_with_distinct_values(self, user_value: str, target_column: str, columns: List[Dict]) -> str:
        """Match user input with actual distinct values using LLM-driven approach"""
        try:
            # Find the target column info
            target_column_info = None
            for col in columns:
                if col.get('name', '').upper() == target_column.upper():
                    target_column_info = col
                    break
            
            if not target_column_info or not target_column_info.get('distinct_values'):
                # No distinct values available, return original
                return user_value
            
            distinct_values = target_column_info.get('distinct_values', [])
            
            # Quick exact match check first
            for distinct_value in distinct_values:
                if str(distinct_value).upper() == user_value.upper():
                    return str(distinct_value)
            
            # Use LLM for semantic matching
            llm = getattr(self, 'llm', None)
            if not llm or len(distinct_values) == 0:
                self.logger.warning("LLM not available or no distinct values", 
                                  has_llm=bool(llm), 
                                  distinct_count=len(distinct_values))
                return user_value
            
            # Build LLM prompt for value matching
            matching_prompt = self._build_value_matching_prompt(user_value, target_column, distinct_values)
            
            # Get LLM response
            response = llm.get_chat().invoke([{"role": "user", "content": matching_prompt}])
            
            # Parse the response (returns dict with match info)
            match_info = self._parse_value_matching_response(response.content, distinct_values, user_value)
            
            # Store match info for state update
            self._store_match_info(target_column, match_info)
            
            # Return the matched value for immediate use
            return match_info['matched_value']
            
        except Exception as e:
            self.logger.error("Failed to match with distinct values", 
                            user_value=user_value, 
                            column=target_column, 
                            error=str(e))
            return user_value
    
    def _build_value_matching_prompt(self, user_value: str, column_name: str, distinct_values: List) -> str:
        """Build LLM prompt for semantic value matching"""
        
        # Send all distinct values for better analysis (no limit)
        # LLM will analyze all values to find the most similar ones
        
        return f"""SEN BİR VERİ ANALİSTİSİN - DEĞER EŞLEŞTİRME ANALİZİ

GÖREV: Kullanıcının girdiği "{user_value}" değeriyle aşağıdaki distinct değerler arasından KELİME BENZERLİĞİ bazında EN YAKIN olanları bul.

KOLON: {column_name}
KULLANICI GİRDİSİ: "{user_value}"

TÜM DISTINCT DEĞERLER:
{chr(10).join([f"{i+1:2d}. {str(val)}" for i, val in enumerate(distinct_values)])}

ANALİZ KRİTERLERİ:
1. KELİME BENZERLİĞİ: Kullanıcı girdisi distinct değer içinde geçiyor mu?
2. SEMANTIC BENZERLİK: Anlamsal olarak ilişkili mi? (dogalgaz ↔ gaz, elektrik ↔ enerji)
3. KISMİ EŞLEŞME: Kısaltma veya kısmi kelime eşleşmesi var mı?

ANALİST YAKLAŞIMI:
- Her distinct değeri "{user_value}" ile karşılaştır
- Kelime benzerliği skorla (0-100)
- En yüksek skora sahip olan(ları) seç
- Eğer hiçbiri %30'un üzerinde değilse: "{user_value}" döndür

ÇOK ÖNEMLİ: 
- Sadece GERÇEK benzerlik varsa eşleştir
- Anlamsız eşleştirmeler yapma (örnek: "dogalgaz" → "YAZILIM" YANLIŞ!)
- JSON format'ta döndür

ÇIKTI FORMATI (JSON):
{{
  "matches": [
    {{
      "value": "Baskent Dogalgaz Dagitim Gayrimenkul Yatirim Ortakligi Anonim Sirketi",
      "similarity": 95,
      "reason": "Kelime benzerliği: dogalgaz"
    }}
  ],
  "original_value": "{user_value}",
  "best_match": "en iyi eşleşen değer buraya"
}}

JSON SONUÇ:"""
    
    def _parse_value_matching_response(self, response: str, distinct_values: List, original_value: str) -> dict:
        """Parse analyst LLM JSON response and return match info"""
        try:
            # Clean the response and extract JSON
            response = response.strip()
            
            # Try to parse JSON response
            import json
            import re
            
            # Find JSON content (handle cases where LLM adds extra text)
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                try:
                    parsed_response = json.loads(json_str)
                except json.JSONDecodeError:
                    # Fix common JSON issues
                    json_str = json_str.replace("'", '"')
                    json_str = re.sub(r'(\w+):', r'"\1":', json_str)  # Fix unquoted keys
                    parsed_response = json.loads(json_str)
                
                # Extract best match from JSON
                best_match = parsed_response.get('best_match', original_value)
                matches = parsed_response.get('matches', [])
                
                # Validate the best match is in our distinct values
                for distinct_value in distinct_values:
                    if str(distinct_value).strip() == best_match.strip():
                        if self._validate_semantic_match(original_value, best_match):
                            match_info = {
                                'matched_value': best_match,
                                'original_value': original_value,
                                'similarity': matches[0].get('similarity', 100) if matches else 100,
                                'reason': matches[0].get('reason', 'Direct match') if matches else 'Direct match'
                            }
                            self.logger.info("JSON Analyst successful match", 
                                           match_info=match_info)
                            return match_info
                        else:
                            self.logger.warning("JSON match validation failed", 
                                              user_input=original_value,
                                              invalid_match=best_match)
            
            # Fallback: Direct substring matching
            for distinct_value in distinct_values:
                val_lower = str(distinct_value).lower()
                orig_lower = original_value.lower()
                
                if orig_lower in val_lower:
                    match_info = {
                        'matched_value': str(distinct_value),
                        'original_value': original_value,
                        'similarity': 100,
                        'reason': f'Kelime benzerliği: {original_value}'
                    }
                    self.logger.info("Fallback substring match", match_info=match_info)
                    return match_info
            
            # No match found
            match_info = {
                'matched_value': original_value,
                'original_value': original_value,
                'similarity': 0,
                'reason': 'No match found'
            }
            self.logger.warning("No valid matches found", 
                              original_value=original_value, 
                              llm_response=response)
            return match_info
            
        except Exception as e:
            self.logger.error("Failed to parse JSON analyst response", error=str(e))
            # Return original value as fallback
            return {
                'matched_value': original_value,
                'original_value': original_value,
                'similarity': 0,
                'reason': 'Parse error'
            }

    def _validate_semantic_match(self, user_input: str, candidate_value: str) -> bool:
        """Validate if a semantic match makes sense"""
        user_lower = user_input.lower()
        candidate_lower = candidate_value.lower()
        
        # Direct substring match is always valid
        if user_lower in candidate_lower:
            return True
        
        # Check for semantic similarity using business terms from config
        business_mappings = business_config.get_business_mappings()
        
        # Find user term in mappings
        for key, synonyms in business_mappings.items():
            if any(synonym in user_lower for synonym in synonyms):
                # Check if candidate contains any of the same synonyms
                if any(synonym in candidate_lower for synonym in synonyms):
                    return True
        
        # If no semantic similarity found, reject
        return False

    def _has_complex_logical_conditions(self, query: str) -> bool:
        """Check if query contains complex logical conditions"""
        query_lower = query.lower()
        
        # Check for logical operators
        logical_operators = ['ve', 'and', 'veya', 'or', 'ya da', 'yada']
        has_logical = any(f' {op} ' in query_lower for op in logical_operators)
        
        # Check for multiple conditions
        condition_indicators = ['olan', 'olanlar', 'olduğu', 'olarak', 'ile', 'göre']
        condition_count = sum(query_lower.count(indicator) for indicator in condition_indicators)
        
        return has_logical or condition_count > 1

    def _add_logical_grouping(self, parameters: Dict, user_query: str) -> Dict:
        """Add logical grouping information for complex WHERE conditions"""
        try:
            where_conditions = parameters.get('where_conditions', [])
            if len(where_conditions) <= 2:
                return parameters  # Simple conditions don't need grouping
            
            # Analyze query for parenthetical logic or priority groupings
            user_query_lower = user_query.lower()
            
            # Check for mixed AND/OR conditions that might need parentheses
            has_and = any(condition.get('logical') == 'AND' for condition in where_conditions[1:])
            has_or = any(condition.get('logical') == 'OR' for condition in where_conditions[1:])
            
            if has_and and has_or:
                # Add grouping markers for mixed logical conditions
                # Group OR conditions together with higher precedence
                grouped_conditions = []
                current_or_group = []
                
                for i, condition in enumerate(where_conditions):
                    if condition.get('logical') == 'OR':
                        current_or_group.append(condition)
                    else:
                        if current_or_group:
                            # Close OR group and add with parentheses marker
                            if len(current_or_group) > 1:
                                for j, or_cond in enumerate(current_or_group):
                                    or_cond['group_start'] = j == 0
                                    or_cond['group_end'] = j == len(current_or_group) - 1
                            grouped_conditions.extend(current_or_group)
                            current_or_group = []
                        
                        grouped_conditions.append(condition)
                
                # Handle remaining OR group
                if current_or_group:
                    if len(current_or_group) > 1:
                        for j, or_cond in enumerate(current_or_group):
                            or_cond['group_start'] = j == 0
                            or_cond['group_end'] = j == len(current_or_group) - 1
                    grouped_conditions.extend(current_or_group)
                
                parameters['where_conditions'] = grouped_conditions
                parameters['has_complex_grouping'] = True
            
        except Exception as e:
            self.logger.error("Failed to add logical grouping", error=str(e))
        
        return parameters

    def _extract_order_by_and_top(self, parameters: Dict, user_query: str) -> Dict:
        """Extract ORDER BY and TOP/LIMIT information from user query"""
        try:
            user_query_lower = user_query.lower()
            
            # Extract ORDER BY information
            order_patterns = [
                # Turkish patterns for ordering - improved specificity
                r'(\w+)\s+nos?(?:ına|una)?\s+göre\s+(?:tersten|ters|descending|azalan|desc)',
                r'(\w+)\s+(?:göre|bazında|üzerinden)\s+(?:tersten|ters|descending|azalan|desc)\s*(?:sırala|sıralan|sıralı)?',
                r'(\w+)\s+(?:göre|bazında|üzerinden)\s+(?:artan|ascending|büyüyen|asc|normal)?\s*(?:sırala|sıralan|sıralı)?',
            ]
            
            import re
            order_by_found = []
            
            for pattern in order_patterns:
                matches = re.finditer(pattern, user_query_lower)
                for match in matches:
                    column_hint = match.group(1).strip()
                    
                    # Map common Turkish terms to actual column names
                    column_mapping = {
                        'belge': 'BelgeNo',
                        'belgeno': 'BelgeNo', 
                        'belgenumara': 'BelgeNo',
                        'tarih': 'BelgeTarih',
                        'belgeTarih': 'BelgeTarih',
                        'tutar': 'NetTutar',
                        'nettutar': 'NetTutar',
                        'kdv': 'KDVTutar',
                        'kdvtutar': 'KDVTutar',
                        'cari': 'CariAdi',
                        'cariad': 'CariAdi',
                        'carikodu': 'CariKodu'
                    }
                    
                    actual_column = column_mapping.get(column_hint, column_hint)
                    
                    # Determine direction
                    direction = 'DESC' if any(desc_word in user_query_lower for desc_word in ['tersten', 'ters', 'descending', 'azalan', 'desc']) else 'ASC'
                    
                    order_by_found.append({
                        'column': actual_column,
                        'direction': direction
                    })
            
            if order_by_found:
                # Remove duplicates while preserving order
                seen_columns = set()
                unique_order_by = []
                for order_item in order_by_found:
                    column = order_item['column']
                    if column not in seen_columns:
                        unique_order_by.append(order_item)
                        seen_columns.add(column)
                
                parameters['order_by'] = unique_order_by
            
            # Extract TOP/LIMIT information
            top_patterns = [
                r'(?:ilk|sadece|yalnızca|only)\s*(\d+)\s*(?:kayıt|adet|row|record)',
                r'(?:top|limit)\s*(\d+)',
                r'(\d+)\s*(?:kayıt|adet|tane)\s*(?:getir|göster|al)'
            ]
            
            for pattern in top_patterns:
                match = re.search(pattern, user_query_lower)
                if match:
                    top_count = int(match.group(1))
                    parameters['top_limit'] = top_count
                    break
            
        except Exception as e:
            self.logger.error("Failed to extract ORDER BY and TOP", error=str(e))
        
        return parameters

    def _enhance_parameters_by_intent(self, parameters: Dict) -> None:
        """Enhance parameters based on intent analysis"""
        try:
            # Get current state to check intent
            intent_analysis = getattr(self, '_current_intent', None)
            if not intent_analysis:
                return
                
            intent_type = intent_analysis.get('intent_type', '')
            target_action = intent_analysis.get('target_action', '').lower()
            
            # If intent is group, ensure GROUP BY is added
            if intent_type == 'group':
                # Check if target mentions specific grouping columns
                if 'cari' in target_action or 'carilere' in target_action:
                    # Add group by for cari columns if not already present
                    if not parameters.get('group_by'):
                        parameters['group_by'] = ['CariKodu', 'CariAdi']
                    
                    # If grouping, ensure we have aggregate functions
                    if not parameters.get('aggregate_functions'):
                        # For KDV tutarı, use SUM
                        if 'kdv' in target_action and 'tutar' in target_action:
                            parameters['aggregate_functions'] = [{
                                'function': 'SUM',
                                'column': 'KDVTutar',
                                'alias': 'ToplamKDVTutar'
                            }]
                            parameters['select_columns'] = ['CariKodu', 'CariAdi', 'SUM(KDVTutar) AS ToplamKDVTutar']
            
            # Ensure proper column mappings
            self._map_columns_to_table_schema(parameters)
            
        except Exception as e:
            self.logger.error("Failed to enhance parameters by intent", error=str(e))
    
    def _map_columns_to_table_schema(self, parameters: Dict) -> None:
        """Map extracted column names to actual table schema"""
        # This will be enhanced with table_info when available
        column_mappings = {
            'kdv_istisna_tutari': 'KDVTutar',
            'kdvtutar': 'KDVTutar',
            'kdv': 'KDVTutar',
            'cari_grup': 'CariGrup',
            'cari_kodu': 'CariKodu',
            'carikodu': 'CariKodu',
            'cari_adi': 'CariAdi',
            'cariad': 'CariAdi',
            'cari_unvan': 'CariUnvan',
            'cariunvan': 'CariUnvan',
            'carigrubu': 'CariGrup',
            'carilar': 'CariKodu'
        }
        
        # Map SELECT columns
        if parameters.get('select_columns'):
            mapped_columns = []
            for col in parameters['select_columns']:
                mapped_col = column_mappings.get(col.lower(), col)
                mapped_columns.append(mapped_col)
            parameters['select_columns'] = mapped_columns
        
        # Map GROUP BY columns
        if parameters.get('group_by'):
            mapped_group = []
            for col in parameters['group_by']:
                mapped_col = column_mappings.get(col.lower(), col)
                mapped_group.append(mapped_col)
            parameters['group_by'] = mapped_group
        
        # Map WHERE conditions
        if parameters.get('where_conditions'):
            for condition in parameters['where_conditions']:
                if condition.get('column'):
                    original_col = condition['column'].lower()
                    mapped_col = column_mappings.get(original_col, condition['column'])
                    condition['column'] = mapped_col
        
        # Map aggregate functions
        if parameters.get('aggregate_functions'):
            for func in parameters['aggregate_functions']:
                if func.get('column'):
                    original_col = func['column'].lower()
                    mapped_col = column_mappings.get(original_col, func['column'])
                    func['column'] = mapped_col
    
    def _create_default_parameters(self) -> Dict:
        """Create default parameters when parsing fails"""
        return {
            "select_columns": ["*"],
            "from_table": "",
            "where_conditions": [],
            "distinct": False,
            "top_limit": None,
            "group_by": [],
            "having_conditions": [],
            "order_by": [],
            "aggregate_functions": [],
            "joins": [],
            "case_when": [],
            "subqueries": [],
            "window_functions": [],
            "date_functions": []
        }
    
    def _format_parameter_result(self, sql_parameters: Dict) -> str:
        """Format parameter extraction result for display"""
        result = "SQL Parameter Extraction Tamamlandı:\n\n"
        
        # Basic query components
        result += f"• **SELECT:** {', '.join(sql_parameters.get('select_columns', ['*']))}\n"
        result += f"• **FROM:** {sql_parameters.get('from_table', 'TBD')}\n"
        result += f"• **DISTINCT:** {'Evet' if sql_parameters.get('distinct') else 'Hayır'}\n"
        
        if sql_parameters.get('top_limit'):
            result += f"• **LIMIT:** {sql_parameters.get('top_limit')}\n"
        
        # WHERE conditions
        where_conditions = sql_parameters.get('where_conditions', [])
        if where_conditions:
            result += f"• **WHERE Koşulları:** {len(where_conditions)} adet\n"
            for i, condition in enumerate(where_conditions[:3]):  # Show first 3
                result += f"  - {condition.get('column', '')} {condition.get('operator', '')} {condition.get('value', '')}\n"
        
        # Aggregate functions
        agg_functions = sql_parameters.get('aggregate_functions', [])
        if agg_functions:
            result += f"• **Toplam Fonksiyonları:** {len(agg_functions)} adet\n"
            for func in agg_functions:
                result += f"  - {func.get('function', '')}({func.get('column', '')})\n"
        
        # GROUP BY
        group_by = sql_parameters.get('group_by', [])
        if group_by:
            result += f"• **GROUP BY:** {', '.join(group_by)}\n"
        
        # ORDER BY
        order_by = sql_parameters.get('order_by', [])
        if order_by:
            order_list = [f"{o.get('column', '')} {o.get('direction', 'ASC')}" for o in order_by]
            result += f"• **ORDER BY:** {', '.join(order_list)}\n"
        
        # JOINs
        joins = sql_parameters.get('joins', [])
        if joins:
            result += f"• **JOINs:** {len(joins)} adet\n"
        
        return result
    
    def _fix_json_format(self, json_str: str) -> str:
        """Fix common JSON formatting issues from LLM responses"""
        try:
            # Remove extra whitespace
            json_str = json_str.strip()
            
            # Fix single quotes to double quotes (common LLM mistake)
            # But be careful not to change quotes inside string values
            import re
            
            # First, protect string content by replacing with placeholders
            string_contents = {}
            placeholder_counter = 0
            
            # Find all string values (content between quotes)
            def replace_strings(match):
                nonlocal placeholder_counter
                content = match.group(0)
                placeholder = f"__STRING_PLACEHOLDER_{placeholder_counter}__"
                string_contents[placeholder] = content
                placeholder_counter += 1
                return placeholder
            
            # Protect double-quoted strings first
            json_str = re.sub(r'"[^"]*"', replace_strings, json_str)
            
            # Now safely replace single quotes with double quotes for keys and values
            json_str = re.sub(r"'([^']*)'", r'"\1"', json_str)
            
            # Restore protected strings
            for placeholder, original in string_contents.items():
                json_str = json_str.replace(placeholder, original)
            
            # Fix common trailing comma issues
            json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
            
            # Fix missing quotes around property names
            json_str = re.sub(r'(\w+):', r'"\1":', json_str)
            
            return json_str
            
        except Exception as e:
            # If fixing fails, return original
            return json_str
    
    def _perform_distinct_value_matching(self, parameters: Dict, state: EnhancedText2SQLState) -> None:
        """Perform distinct value matching using LLM tool and update state"""
        try:
            # Initialize _match_results if not exists
            if not hasattr(self, '_match_results'):
                self._match_results = {}
            
            # Get table info from state
            table_info = state.get("table_info", {})
            if not table_info or not table_info.get("columns"):
                self.logger.debug("Distinct value matching skipped: missing table_info or columns")
                return
                
            # Get user query - try multiple sources for reliability
            user_query = getattr(self, '_current_user_query', '')
            if not user_query:
                # Fallback: extract from state messages
                for msg in state.get("messages", []):
                    if hasattr(msg, 'content') and isinstance(msg.content, str):
                        user_query = msg.content
                        break
                    elif isinstance(msg, dict) and msg.get("role") == "user":
                        user_query = str(msg.get("content", ""))
                        break
            
            if not user_query:
                self.logger.debug("Distinct value matching skipped: no user query found")
                return
            
            # Get WHERE conditions that need value matching
            where_conditions = parameters.get('where_conditions', [])
            if not where_conditions:
                self.logger.debug("Distinct value matching skipped: no WHERE conditions found")
                return
            
            # Log attempt for debugging
            self.logger.info("Starting distinct value matching", 
                           user_query=user_query[:100], 
                           conditions_count=len(where_conditions))
            
            # Build distinct value matching prompt
            matching_prompt = self._build_distinct_value_matching_prompt(
                user_query, table_info, where_conditions
            )
            
            # Call LLM for distinct value matching
            response = self.llm.get_chat().invoke([{"role": "user", "content": matching_prompt}])
            
            # Parse and store matches
            matches = self._parse_distinct_value_matches(response.content)
            if matches:
                self._match_results.update(matches)
                state["distinct_value_matches"] = matches
                
                # Add ToolMessage to state
                tool_msg = f"Distinct Value Matching tamamlandı: {len(matches)} eşleşme bulundu"
                state["messages"].append(ToolMessage(content=tool_msg, tool_call_id="distinct_value_matching"))
                
                self.logger.info("Distinct value matching completed", matches_found=len(matches))
            else:
                self.logger.warning("Distinct value matching completed but no matches found")
            
        except Exception as e:
            self.logger.error("Distinct value matching failed", error=str(e), exc_info=True)
    
    def _build_distinct_value_matching_prompt(self, user_query: str, table_info: Dict, where_conditions: List) -> str:
        """Build prompt for distinct value matching"""
        columns_info = []
        for col in table_info.get("columns", []):
            col_name = col.get("name", "")
            distinct_values = col.get("distinct_values", [])
            if distinct_values and len(distinct_values) <= 20:  # Only include columns with distinct values
                try:
                    # Safely handle distinct values that might contain None or non-string types
                    safe_values = [str(v) for v in distinct_values if v is not None][:10]
                    distinct_str = ", ".join([f"'{v}'" for v in safe_values])
                    columns_info.append(f"- {col_name}: {distinct_str}")
                except Exception as e:
                    self.logger.warning(f"Skipping column {col_name} due to value processing error: {e}")
        
        conditions_str = ""
        for i, cond in enumerate(where_conditions):
            try:
                column = str(cond.get("column", "")) if cond.get("column") else ""
                value = str(cond.get("value", "")) if cond.get("value") else ""
                if column and value:  # Only add valid conditions
                    conditions_str += f"{i+1}. {column} = {value}\n"
            except Exception as e:
                self.logger.warning(f"Skipping condition {i+1} due to processing error: {e}")
        
        return f"""DISTINCT VALUE MATCHING GÖREVI

Kullanıcı Sorusu: "{user_query}"

WHERE Koşulları:
{conditions_str}

Tablo Kolonları ve Distinct Değerleri:
{chr(10).join(columns_info)}

GÖREVİN:
1. WHERE koşullarındaki değerleri, tablo kolonlarının distinct değerleriyle karşılaştır
2. En uygun eşleşmeleri bul (tam eşleşme veya benzer değerler)
3. Sonucu JSON formatında döndür

ÇIKTI FORMATI:
```json
{{
    "matches": {{
        "column_name": {{
            "original_value": "kullanıcının girdiği değer",
            "matched_value": "tablodaki gerçek değer",
            "confidence": 0.95
        }}
    }}
}}
```

KURALLAR:
- Makul güven skorlu eşleşmeleri dahil et (>0.4)
- Türkçe karakterleri ve kelime benzerliklerini dikkate al
- Büyük/küçük harf farklarını göz ardı et
- Kısmi kelime eşleşmeleri de değerlendir (örn: "dogalgz" -> "Dogalgaz")
- Tarih formatlarını özellikle dikkat et (MM/YYYY vs YYYY-MM)"""
    
    def _parse_distinct_value_matches(self, response_content: str) -> Dict:
        """Parse distinct value matches from LLM response"""
        try:
            # Extract JSON from response
            import json
            import re
            
            json_match = re.search(r'```json\s*({.*?})\s*```', response_content, re.DOTALL)
            if not json_match:
                # Try to find JSON without code blocks
                json_match = re.search(r'({.*?})', response_content, re.DOTALL)
            
            if json_match:
                json_str = json_match.group(1)
                matches_data = json.loads(json_str)
                return matches_data.get("matches", {})
            
            return {}
            
        except Exception as e:
            self.logger.error("Failed to parse distinct value matches", error=str(e))
            return {}


class SQLGenerationAgent:
    """Specialized Agent for SQL generation using LLM with intent analysis"""
    
    def __init__(self, llm, logger):
        self.llm = llm
        self.logger = logger
        
    def execute(self, state: EnhancedText2SQLState, *, config) -> EnhancedText2SQLState:
        """Execute SQL generation workflow using extracted SQL parameters"""
        state["current_agent"] = "sql_generation_agent"
        
        try:
            # Get required data from state
            table_info = state.get("table_info", {})
            intent_analysis = state.get("intent_analysis", {})
            context_analysis = state.get("context_analysis", {})
            sql_parameters = state.get("sql_parameters", {})
            distinct_value_matches = state.get("distinct_value_matches", {})
            
            # Log what we have in state for debugging
            self.logger.info("SQL Generation Agent state check",
                           has_distinct_matches=bool(distinct_value_matches),
                           distinct_matches_keys=list(distinct_value_matches.keys()) if distinct_value_matches else [],
                           has_where_conditions=bool(sql_parameters.get("where_conditions")),
                           where_conditions_count=len(sql_parameters.get("where_conditions", [])))
            
            # CRITICAL: Update sql_parameters with distinct value matches BEFORE building prompt
            if distinct_value_matches and sql_parameters.get("where_conditions"):
                self.logger.info("Applying distinct matches to SQL parameters", 
                               matches_available=list(distinct_value_matches.keys()),
                               conditions_count=len(sql_parameters.get("where_conditions", [])))
                sql_parameters = self._apply_distinct_matches_to_parameters(sql_parameters, distinct_value_matches)
                self.logger.info("Updated SQL parameters after applying distinct matches",
                               updated_conditions=[{
                                   "column": c.get("column"), 
                                   "value": c.get("value")
                               } for c in sql_parameters.get("where_conditions", [])])
            else:
                self.logger.warning("Skipping distinct value matching",
                                  reason="No distinct matches or no where conditions",
                                  has_distinct_matches=bool(distinct_value_matches),
                                  has_where_conditions=bool(sql_parameters.get("where_conditions")))
            
            # If table_info is missing, get it from config
            if not table_info:
                configurable = config.get("configurable", {})
                assistant_config = configurable.get("assistant_config", {})
                table_info = {
                    "table_name": assistant_config.get("table_name", ""),
                    "columns": assistant_config.get("table_columns", []),
                    "description": assistant_config.get("table_description", "")
                }
            
            if not table_info.get("table_name") or not intent_analysis or not sql_parameters:
                error_msg = "Required data (table_info, intent_analysis, or sql_parameters) not found"
                state["errors"] = {"error_message": error_msg}
                return state
            
            # Get original user query
            user_query = ""
            for msg in state.get("messages", []):
                if hasattr(msg, 'content') and isinstance(msg, HumanMessage):
                    msg_content = msg.content
                    if isinstance(msg_content, list):
                        msg_content = ' '.join(str(item) for item in msg_content)
                    user_query = str(msg_content)
                    break
            
            # Build SQL generation prompt using extracted parameters
            sql_prompt = self._build_sql_generation_prompt(
                user_query, table_info, intent_analysis, context_analysis, sql_parameters, distinct_value_matches
            )
            
            self.logger.info("SQL Generation Prompt built",
                           prompt_length=len(sql_prompt),
                           where_conditions_in_prompt=sql_prompt.count("[") - sql_prompt.count("FROM: ["))
            
            # Log critical parts of the prompt for debugging
            if "WHERE Koşulları" in sql_prompt:
                where_section = sql_prompt[sql_prompt.find("WHERE Koşulları"):sql_prompt.find("KOLON EŞLEŞTİRME")]
                self.logger.info("WHERE conditions in prompt", where_section=where_section.strip())
            
            # Generate SQL using LLM
            response = self.llm.get_chat().invoke([{"role": "user", "content": sql_prompt}])
            
            # Extract SQL from response using enhanced cleaner
            from src.utils.sql_cleaner import extract_sql_from_response
            generated_sql = extract_sql_from_response(response.content) or self._extract_sql_from_response(response.content)
            
            state["sql_query"] = generated_sql
            state["execution_status"] = "success" if generated_sql else "failed"
            
            # Create result message - only SQL code
            if generated_sql:
                state["messages"].append(ToolMessage(content=generated_sql, tool_call_id="sql_generation"))
            else:
                state["messages"].append(ToolMessage(content="SQL oluşturulamadı", tool_call_id="sql_generation"))
            
            # Store agent results
            if "agent_results" not in state:
                state["agent_results"] = {}
            state["agent_results"]["sql_generation_agent"] = {
                "status": "success" if generated_sql else "error",
                "data": {"sql_query": generated_sql, "intent_used": intent_analysis},
                "message": generated_sql if generated_sql else "SQL oluşturulamadı"
            }
            
            self.logger.info("SQL Generation Agent completed successfully", 
                           intent_type=intent_analysis.get('intent_type'),
                           sql_generated=bool(generated_sql))
            return state
            
        except Exception as e:
            error_msg = f"SQL Generation Agent failed: {str(e)}"
            state["errors"] = {"error_message": error_msg}
            state["execution_status"] = "failed"
            state["messages"].append(ToolMessage(content=error_msg, tool_call_id="sql_generation"))
            
            if "agent_results" not in state:
                state["agent_results"] = {}
            state["agent_results"]["sql_generation_agent"] = {
                "status": "error",
                "error": str(e),
                "message": error_msg
            }
            
            self.logger.error("SQL Generation Agent failed", error=str(e))
            return state
    
    def _apply_distinct_matches_to_parameters(self, sql_parameters: Dict, distinct_value_matches: Dict) -> Dict:
        """Apply distinct value matches to WHERE conditions in sql_parameters"""
        try:
            # Make a deep copy to avoid modifying original
            import copy
            updated_parameters = copy.deepcopy(sql_parameters)
            where_conditions = updated_parameters.get("where_conditions", [])
            
            if not where_conditions:
                return updated_parameters
            
            # Update each WHERE condition with matched values
            for condition in where_conditions:
                column = condition.get("column", "")
                original_value = condition.get("value", "")
                operator = condition.get("operator", "=")
                
                # Check if there's a match for this column (case-insensitive)
                column_match_key = None
                for key in distinct_value_matches.keys():
                    if key.upper() == column.upper():
                        column_match_key = key
                        break
                
                if column_match_key:
                    match_info = distinct_value_matches[column_match_key]
                    matched_value = match_info.get("matched_value") or match_info.get("best_match", "")
                    confidence = match_info.get("confidence", 0)
                    
                    # CRITICAL FIX: Lower confidence threshold and better logic
                    # Use matched value if confidence is reasonable (was 0.7, now 0.4)
                    if confidence >= 0.4 and matched_value:
                        # Clean the matched value (remove quotes if present)
                        clean_matched = matched_value.strip("'\"")
                        
                        # CRITICAL FIX: Handle different operators properly
                        if operator == "LIKE":
                            # For LIKE operations, preserve the pattern format
                            if original_value.startswith("'%") and original_value.endswith("%'"):
                                condition["value"] = f"'%{clean_matched}%'"
                            else:
                                condition["value"] = f"'{clean_matched}'"
                        elif operator == "=":
                            # For exact matches, use clean value
                            condition["value"] = f"'{clean_matched}'"
                        else:
                            # For other operators, use clean value
                            condition["value"] = f"'{clean_matched}'"
                        
                        self.logger.info(f"Applied distinct match to SQL parameters: {column} {operator} '{original_value}' → '{clean_matched}' (confidence: {confidence})")
            
            return updated_parameters
            
        except Exception as e:
            self.logger.error("Failed to apply distinct matches to parameters", error=str(e))
            return sql_parameters
    
    def _build_sql_generation_prompt(self, user_query: str, table_info: Dict, 
                                   intent_analysis: Dict, context_analysis: Dict, 
                                   sql_parameters: Dict, distinct_value_matches: Dict = None) -> str:
        """Build enhanced SQL generation prompt using extracted SQL parameters"""
        
        table_name = table_info.get("table_name", "")
        columns = table_info.get("columns", [])
        
        # Schema-aware validation and parameter correction
        validated_parameters = self._validate_schema_parameters(sql_parameters, columns)
        
        # Format columns with types only (no distinct values to keep prompt clean)
        column_info = []
        for col in columns:
            col_name = col.get("name", "")
            col_type = col.get("type", "")
            
            # Add brief description for common column types
            type_description = self._get_column_type_description(col_type)
            if type_description:
                column_info.append(f"  - [{col_name}] ({col_type}) - {type_description}")
            else:
                column_info.append(f"  - [{col_name}] ({col_type})")
        
        # Format validated SQL parameters with distinct value matches
        parameters_info = self._format_sql_parameters(validated_parameters, table_name, distinct_value_matches)
        
        # Create column suggestions for better matching
        column_suggestions = self._create_column_suggestions(columns, validated_parameters)
        
        # Intent-based SQL enhancement
        intent_guidance = self._create_intent_guidance(intent_analysis, validated_parameters)
        
        return f"""MSSQL QUERY GENERATION TASK

KULLANICI SORGUSU: "{user_query}"

VERİTABANI BİLGİLERİ:
Tablo: [{table_name}]
Tüm Kolonlar:
{chr(10).join(column_info)}

ÇIKARILAN SQL PARAMETRELERİ(Buradaki değerler AYNEN kullanılmalıdır):
{parameters_info}

KOLON EŞLEŞTİRME ÖNERİLERİ:
{column_suggestions}

INTENT-BASED SQL GUIDANCE:
{intent_guidance}

GÖREV: Çıkarılan parametreleri ve intent guidance'ı kullanarak tam SQL sorgusu oluştur.

KURALLAR:
1. **KRİTİK: Çıkarılan parametreleri AYNEN ve TAM OLARAK kullan - hiçbir değeri değiştirme, kısaltma veya yorumlama yapma**
2. [{table_name}] tablosunu FROM kısmında kullan
3. Kolon isimlerini MUTLAKA köşeli parantezle yazın: [KolonAdi]
4. MSSQL syntax kullan (TOP, MSSQL fonksiyonları)
5. Sadece çalıştırılabilir SQL döndür, açıklama yok
6. WHERE koşullarını belirtilen operatörlerle ve logical operatörlerle oluştur
7. Aggregate fonksiyonları varsa GROUP BY ekle
8. Kolon eşleştirme önerilerini dikkate al - tam eşleşme bulamazsan benzer olanı kullan
9. Logical operatörleri (AND/OR) WHERE koşulları arasında doğru şekilde kullan
10. Parantez kullanımına dikkat et - kompleks logical yapılarda parantezle grupla
11. **MUTLAK KURAL: WHERE koşulunu yanındaki verilen değerlerle AYNEN oluştur - string değerleri kısaltma**
12. **ÖNEMLİ: Sayısal değerleri tek tırnak içine alma (örn: > 100, > '100' DEĞİL)**
13. **KRİTİK: String değerleri parametrelerde verildiği şekliyle tam olarak kullan**

ÖNEMLİ UYARILAR:
- Parametrelerde belirtilen kolon adları tabloda yoksa, kolon önerileri listesinden en uygun olanı seç
- Hiçbir parametre değerini yorumlama, kısaltma veya değiştirme - AYNEN kullan
- String değerler için parametrelerde verilen tam metni kullan
- Sayısal karşılaştırmalar için tek tırnak kullanma

OLUŞTURULACAK SQL:"""
    def _create_column_suggestions(self, columns: List[Dict], sql_parameters: Dict) -> str:
        """Create column matching suggestions for SQL generation"""
        suggestions = []
        
        # Get all column names from table
        table_columns = [col.get("name", "") for col in columns if col.get("name")]
        
        # Get columns mentioned in parameters
        param_columns = set()
        
        # From SELECT
        select_cols = sql_parameters.get('select_columns', [])
        for col in select_cols:
            if col != '*':
                param_columns.add(col.upper())
        
        # From WHERE conditions
        where_conditions = sql_parameters.get('where_conditions', [])
        for condition in where_conditions:
            if condition.get('column'):
                param_columns.add(condition.get('column').upper())
        
        # From GROUP BY
        group_by = sql_parameters.get('group_by', [])
        for col in group_by:
            param_columns.add(col.upper())
        
        # From ORDER BY
        order_by = sql_parameters.get('order_by', [])
        for item in order_by:
            if item.get('column'):
                param_columns.add(item.get('column').upper())
        
        # From aggregate functions
        agg_functions = sql_parameters.get('aggregate_functions', [])
        for func in agg_functions:
            if func.get('column'):
                param_columns.add(func.get('column').upper())
        
        # Create suggestions for each parameter column
        for param_col in param_columns:
            best_match = self._find_best_column_match(param_col, table_columns)
            if best_match != param_col:
                suggestions.append(f"'{param_col}' -> '[{best_match}]' (en uygun eşleşme)")
            else:
                suggestions.append(f"'{param_col}' -> '[{param_col}]' (tam eşleşme)")
        
        return '\n'.join(suggestions) if suggestions else "Tüm parametreler tabloda mevcut kolonlarla eşleşiyor."
    
    def _create_intent_guidance(self, intent_analysis: Dict, sql_parameters: Dict) -> str:
        """Create intent-based SQL guidance"""
        intent_type = intent_analysis.get('intent_type', '')
        target_action = intent_analysis.get('target_action', '')
        
        guidance = []
        
        if intent_type == 'group':
            guidance.append("[CHART] GRUPLAMA İNTENTİ TESPİT EDİLDİ:")
            guidance.append("- GROUP BY kullanılması zorunludur")
            guidance.append("- Aggregate fonksiyonlar (SUM, COUNT, AVG) kullanılmalıdır")
            
            if 'cari' in target_action.lower():
                guidance.append("- Cari bilgilerine göre gruplama yapılacak")
                guidance.append("- Önerilen GROUP BY: [CariKodu], [CariAdi] veya [CariUnvan]")
            
            if 'kdv' in target_action.lower() and 'tutar' in target_action.lower():
                guidance.append("- KDV tutarları toplanmalı: SUM([KDVTutar])")
                guidance.append("- SELECT: [CariKodu], [CariAdi], SUM([KDVTutar]) AS ToplamKDVTutar")
        
        elif intent_type == 'sum':
            guidance.append("[MONEY] TOPLAMA İNTENTİ TESPİT EDİLDİ:")
            guidance.append("- SUM() fonksiyonu kullanılmalıdır")
            guidance.append("- Numeric kolonlar için toplama yapılmalı")
        
        elif intent_type == 'count':
            guidance.append("🔢 SAYIM İNTENTİ TESPİT EDİLDİ:")
            guidance.append("- COUNT() fonksiyonu kullanılmalıdır")
            guidance.append("- Kayıt sayısı döndürülmeli")
        
        elif intent_type == 'list':
            guidance.append("📋 LİSTELEME İNTENTİ TESPİT EDİLDİ:")
            guidance.append("- SELECT kolonları belirtilmeli")
            guidance.append("- Filtreleme varsa WHERE kullanılmalı")
        
        # Special cases
        if 'istisna' in target_action.lower():
            guidance.append("[WARNING] İSTİSNA DURUMU:")
            guidance.append("- KDVIskontosu veya sıfır KDV durumları için kontrol eklenebilir")
            guidance.append("- WHERE [KDVOran] = 0 veya [KDVIskontosu] > 0 koşulu düşünülebilir")
        
        return '\n'.join(guidance) if guidance else "Genel SQL oluşturma kuralları uygulanacak"


    def _find_best_column_match(self, param_column: str, table_columns: List[str]) -> str:
        """Find the best matching column name from table columns"""
        param_upper = param_column.upper()
        
        # First try exact match
        for col in table_columns:
            if col.upper() == param_upper:
                return col
        
        # Then try partial matches with common substitutions
        substitutions = {
            'BELGETURU': ['BELGETIPI', 'BELGETUR'],
            'BELGETIPI': ['BELGETURU', 'BELGETUR'],
            'NETTUTAR': ['NETTUTARDAHIL', 'NET_TUTAR', 'NETTUTAR_DAHIL'],
            'NETTUTARDAHIL': ['NETTUTAR', 'NET_TUTAR_DAHIL'],
            'CARI': ['CARIKODU', 'CARIUNVAN', 'CARI_KODU'],
            'CARIKODU': ['CARI', 'CARI_KODU'],
            'CARIUNVAN': ['CARI', 'CARI_UNVAN'],
        }
        
        # Check substitutions
        if param_upper in substitutions:
            for alternative in substitutions[param_upper]:
                for col in table_columns:
                    if col.upper() == alternative:
                        return col
        
        # Try contains matching
        for col in table_columns:
            col_upper = col.upper()
            if param_upper in col_upper or col_upper in param_upper:
                return col
        
        # If no match found, return original
        return param_column

    def _get_final_value_with_threshold(self, column: str, original_value: str, distinct_value_matches: Dict) -> str:
        """Get final value using distinct matches with similarity threshold"""
        try:
            # Remove quotes from original value for comparison
            clean_original = original_value.strip('\'"')
            
            self.logger.debug(f"Getting final value for column={column}, original={clean_original}, available_matches={list(distinct_value_matches.keys())}")
            
            # Check if we have a match for this column (case-insensitive)
            column_match_key = None
            for key in distinct_value_matches.keys():
                if key.upper() == column.upper():
                    column_match_key = key
                    break
            
            if column_match_key:
                match_info = distinct_value_matches[column_match_key]
                
                # Handle both old format (matched_value, similarity) and new format (best_match, similarity)
                similarity = match_info.get('confidence', 0)
                matched_value = match_info.get('matched_value') or match_info.get('best_match', clean_original)
                
                self.logger.debug(f"Column match found: matched_value={matched_value}, similarity={similarity}")
                # Similarity threshold: use matched value if similarity >= 0.70
                if float(similarity) >= 0.70:
                    # Log the substitution
                    if matched_value != clean_original:
                        self.logger.info("Using distinct value match in SQL generation", 
                                       column=column,
                                       original=clean_original,
                                       matched=matched_value,
                                       similarity=similarity)
                    return f"'{matched_value}'"  # Always quote the final value
                else:
                    # Low similarity, use original value
                    self.logger.info("Low similarity, using original value", 
                                   column=column,
                                   original=clean_original,
                                   similarity=similarity)
                    return f"'{clean_original}'"
            
            # Check if we have a global match (not column-specific)
            # Handle JSON format where we need to check all matches for this original value
            else:
                for key, match_info in distinct_value_matches.items():
                    if isinstance(match_info, dict) and match_info.get('original_value') == clean_original:
                        similarity = match_info.get('similarity', 0)
                        matched_value = match_info.get('matched_value') or match_info.get('best_match', clean_original)
                        
                        self.logger.debug(f"Global match found: matched_value={matched_value}, similarity={similarity}")
                        
                        # Use matched value if similarity >= 70%
                        if similarity >= 70:
                            self.logger.info("Using global distinct value match in SQL generation", 
                                           original=clean_original,
                                           matched=matched_value,
                                           similarity=similarity)
                            return f"'{matched_value}'"
                        break
            
            # No match found, use original
            self.logger.debug(f"No match found for {clean_original}, using original value")
            return f"'{clean_original}'"
            
        except Exception as e:
            self.logger.error("Failed to get final value with threshold", 
                            column=column, 
                            original=original_value,
                            error=str(e))
            return original_value
    
    
    def _format_sql_parameters(self, sql_parameters: Dict, table_name: str, distinct_value_matches: Dict = None) -> str:
        """Format SQL parameters for prompt display with distinct value matching"""
        params_text = []
        distinct_value_matches = distinct_value_matches or {}
        
        # SELECT
        select_columns = sql_parameters.get('select_columns', ['*'])
        if sql_parameters.get('from_table'):
            table_name = sql_parameters.get('from_table')
        params_text.append(f"SELECT: {', '.join(select_columns)}")
        
        # FROM
        params_text.append(f"FROM: [{table_name}]")
        
        # DISTINCT
        if sql_parameters.get('distinct'):
            params_text.append("DISTINCT: Evet")
        
        # TOP/LIMIT
        if sql_parameters.get('top_limit'):
            params_text.append(f"TOP: {sql_parameters.get('top_limit')}")
        
        # WHERE conditions with enhanced logical operator handling and distinct value matching
        where_conditions = sql_parameters.get('where_conditions', [])
        if where_conditions:
            params_text.append(f"WHERE Koşulları: {len(where_conditions)} adet")
            for i, condition in enumerate(where_conditions):
                logical = condition.get('logical', '') if i > 0 else ""
                logical_prefix = f"{logical} " if logical else ""
                column = condition.get('column', '')
                operator = condition.get('operator', '')
                value = condition.get('value', '')
                
                # CRITICAL: Use distinct value matches with similarity threshold - for display only
                final_value = self._get_final_value_with_threshold(column, value, distinct_value_matches)
                # Don't modify the condition here, only use for display
                # Handle grouping for parentheses
                group_start = "(" if condition.get('group_start') else ""
                group_end = ")" if condition.get('group_end') else ""
                
                # Format value properly for display
                if operator == 'LIKE':
                    final_value = f"'%{final_value.strip('\'')}%'" if not final_value.startswith("'%") else final_value
                elif operator == 'BETWEEN':
                    # Handle BETWEEN values (should be two values)
                    values = final_value.strip('\'"').split(' AND ')
                    if len(values) == 2:
                        final_value = f"'{values[0]}' AND '{values[1]}'"
                
                condition_text = f"{group_start}[{column}] {operator} {final_value}{group_end}"
                params_text.append(f"  {logical_prefix}{condition_text}")
        
        # Aggregate functions
        agg_functions = sql_parameters.get('aggregate_functions', [])
        if agg_functions:
            params_text.append("Toplam Fonksiyonları:")
            for func in agg_functions:
                alias = f" AS [{func.get('alias', '')}]" if func.get('alias') else ""
                params_text.append(f"  {func.get('function', '')}([{func.get('column', '')}]){alias}")
        
        # GROUP BY
        group_by = sql_parameters.get('group_by', [])
        if group_by:
            params_text.append(f"GROUP BY: {', '.join([f'[{col}]' for col in group_by])}")
        
        # HAVING conditions
        having_conditions = sql_parameters.get('having_conditions', [])
        if having_conditions:
            params_text.append(f"HAVING Koşulları: {len(having_conditions)} adet")
        
        # ORDER BY
        order_by = sql_parameters.get('order_by', [])
        if order_by:
            order_list = [f"[{o.get('column', '')}] {o.get('direction', 'ASC')}" for o in order_by]
            params_text.append(f"ORDER BY: {', '.join(order_list)}")
        
        # JOINs
        joins = sql_parameters.get('joins', [])
        if joins:
            params_text.append(f"JOINs: {len(joins)} adet")
            for join in joins:
                params_text.append(f"  {join.get('type', 'INNER')} JOIN [{join.get('table', '')}] ON {join.get('condition', '')}")
        
        return '\n'.join(params_text)
    
    def _validate_schema_parameters(self, sql_parameters: Dict, table_columns: List[Dict]) -> Dict:
        """Validate and correct SQL parameters against table schema"""
        validated_params = sql_parameters.copy()
        available_columns = [col.get("name", "") for col in table_columns if col.get("name")]
        validation_log = []
        
        def find_best_column_match(param_col: str) -> str:
            """Find best matching column or return None if not found"""
            param_upper = param_col.upper()
            
            # Exact match first
            for col in available_columns:
                if col.upper() == param_upper:
                    return col
            
            # Fuzzy matching with common patterns
            fuzzy_matches = {
                'KDV': ['KDVTUTAR', 'KDVORANA', 'KDV_TUTAR'],
                'KDVTUTAR': ['KDV', 'KDVTUTARI', 'KDV_TUTAR'],
                'CARI': ['CARIKODU', 'CARIAD', 'CARIUNVAN'],
                'CARIAD': ['CARI_ADI', 'CARIUNVAN', 'CARI'],
                'CARIKODU': ['CARI_KODU', 'CARI', 'CARIKOD'],
                'ISTISNA': ['KDVISTISNA', 'KDV_ISTISNA', 'KDVISKONTOSU'],
                'BELGETURU': ['BELGETIPI', 'BELGE_TIPI', 'BELGE_TURU'],
                'BELGETIPI': ['BELGETURU', 'BELGE_TIPI', 'BELGE_TURU']
            }
            
            # CRITICAL FIX: Do NOT map CariKodu to Tur - they are different columns
            # CariKodu should stay as CariKodu
            if param_upper == 'CARIKODU':
                for col in available_columns:
                    if col.upper() == 'CARIKODU':
                        return col
            
            # TUR is a different column - don't mix with CariKodu
            
            if param_upper in fuzzy_matches:
                for alternative in fuzzy_matches[param_upper]:
                    for col in available_columns:
                        if col.upper() == alternative:
                            validation_log.append(f"Column mapping: {param_col} -> {col}")
                            return col
            
            # Contains matching
            for col in available_columns:
                if param_upper in col.upper() or col.upper() in param_upper:
                    validation_log.append(f"Partial match: {param_col} -> {col}")
                    return col
            
            validation_log.append(f"Column not found in schema: {param_col} (removed)")
            return None
        
        # Validate SELECT columns
        if validated_params.get('select_columns'):
            valid_columns = []
            for col in validated_params['select_columns']:
                if col == '*':
                    valid_columns.append(col)
                else:
                    matched_col = find_best_column_match(col)
                    if matched_col:
                        valid_columns.append(matched_col)
            validated_params['select_columns'] = valid_columns or ['*']
        
        # Validate WHERE conditions
        if validated_params.get('where_conditions'):
            valid_conditions = []
            for condition in validated_params['where_conditions']:
                col_name = condition.get('column')
                if col_name:
                    matched_col = find_best_column_match(col_name)
                    if matched_col:
                        condition['column'] = matched_col
                        valid_conditions.append(condition)
            validated_params['where_conditions'] = valid_conditions
        
        # Validate GROUP BY columns
        if validated_params.get('group_by'):
            valid_group = []
            for col in validated_params['group_by']:
                matched_col = find_best_column_match(col)
                if matched_col:
                    valid_group.append(matched_col)
            validated_params['group_by'] = valid_group
        
        # Validate ORDER BY columns
        if validated_params.get('order_by'):
            valid_order = []
            for item in validated_params['order_by']:
                col_name = item.get('column')
                if col_name:
                    matched_col = find_best_column_match(col_name)
                    if matched_col:
                        item['column'] = matched_col
                        valid_order.append(item)
            validated_params['order_by'] = valid_order
        
        # Validate aggregate function columns
        if validated_params.get('aggregate_functions'):
            valid_aggs = []
            for func in validated_params['aggregate_functions']:
                col_name = func.get('column')
                if col_name:
                    matched_col = find_best_column_match(col_name)
                    if matched_col:
                        func['column'] = matched_col
                        valid_aggs.append(func)
            validated_params['aggregate_functions'] = valid_aggs
        
        # Log validation results
        if validation_log:
            self.logger.info("Schema validation completed", changes=validation_log)
        
        return validated_params

    def _extract_sql_from_response(self, response_content: str) -> Optional[str]:
        """Extract SQL query from LLM response"""
        try:
            import re
            
            # Clean the response first
            cleaned_response = response_content.strip()
            
            # Try different SQL extraction patterns
            sql_patterns = [
                r'```sql\n(.*?)\n```',
                r'```\n(.*?)\n```', 
                r'OLUŞTURULACAK SQL:\s*(.*?)(?:\n\n|$)',
                r'SQL:\s*(.*?)(?:\n\n|$)',
                r'(SELECT.*?)(?:\n\n|$)',
                r'(INSERT.*?)(?:\n\n|$)', 
                r'(UPDATE.*?)(?:\n\n|$)',
                r'(DELETE.*?)(?:\n\n|$)',
                r'(WITH.*?)(?:\n\n|$)'
            ]
            
            for pattern in sql_patterns:
                match = re.search(pattern, cleaned_response, re.DOTALL | re.IGNORECASE)
                if match:
                    sql = match.group(1).strip()
                    # Clean up SQL
                    sql = re.sub(r'\s+', ' ', sql)  # Replace multiple spaces/newlines with single space
                    sql = sql.replace('```', '').strip()
                    
                    # Validate that it's actually SQL
                    if any(keyword in sql.upper() for keyword in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'WITH']):
                        return sql
            
            # If no pattern matches, check if the entire response is SQL
            if any(keyword in cleaned_response.upper() for keyword in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'WITH']):
                # Clean up the SQL
                sql = re.sub(r'\s+', ' ', cleaned_response.strip())
                sql = sql.replace('```', '').replace('sql', '').strip()
                return sql
            
            return None
        except Exception:
            return None
    
    def _get_column_type_description(self, col_type: str) -> str:
        """Get brief description for common column types"""
        if not col_type:
            return ""
            
        col_type_upper = col_type.upper()
        
        # Common SQL Server data types with descriptions
        type_descriptions = {
            'VARCHAR': 'metin değeri',
            'NVARCHAR': 'unicode metin',
            'CHAR': 'sabit uzunluk metin',
            'NCHAR': 'sabit uzunluk unicode metin',
            'TEXT': 'uzun metin',
            'NTEXT': 'uzun unicode metin',
            'INT': 'tam sayı',
            'INTEGER': 'tam sayı',
            'BIGINT': 'büyük tam sayı',
            'SMALLINT': 'küçük tam sayı',
            'TINYINT': 'çok küçük tam sayı',
            'DECIMAL': 'ondalık sayı',
            'NUMERIC': 'sayısal değer',
            'FLOAT': 'ondalık sayı',
            'REAL': 'ondalık sayı',
            'MONEY': 'para birimi',
            'SMALLMONEY': 'küçük para birimi',
            'DATETIME': 'tarih ve saat',
            'SMALLDATETIME': 'tarih ve saat',
            'DATE': 'tarih',
            'TIME': 'saat',
            'DATETIME2': 'gelişmiş tarih saat',
            'DATETIMEOFFSET': 'zaman dilimli tarih',
            'BIT': 'boolean (0/1)',
            'UNIQUEIDENTIFIER': 'benzersiz kimlik',
            'BINARY': 'ikili veri',
            'VARBINARY': 'değişken ikili veri',
            'IMAGE': 'resim verisi'
        }
        
        # Extract base type (remove length specifications like VARCHAR(50))
        base_type = col_type_upper.split('(')[0].strip()
        
        return type_descriptions.get(base_type, "")


@register_graph("enhanced_query_extraction_old")
class EnhancedQueryExtractionGraph(BaseGraph):
    """Enhanced Query Extraction Graph - Multi-Agent Architecture with specialized agents, tools, and graph orchestration"""
    
    def __init__(self, llm, db: SQLDatabase = None, memory: MemorySaver = None):
        super().__init__(llm=llm, state_class=EnhancedText2SQLState, memory=memory)
        self.logger = log.get(module="enhanced_query_extraction_graph")
        self.db = db if db is not None else SQLDatabase.from_uri(config.database.uri)
        self._initialize_agents()
        self.logger.info("Enhanced Query Extraction Multi-Agent Graph initialized")

    def _initialize_agents(self):
        """Initialize specialized agents"""
        self.table_data_agent = TableDataAgent(self.db, self.logger)
        self.context_analysis_agent = ContextAnalysisAgent(self.logger)
        self.intent_analysis_agent = IntentAnalysisAgent(self.llm, self.logger)
        self.sql_parameter_extraction_agent = SQLParameterExtractionAgent(self.llm, self.logger)
        self.sql_generation_agent = SQLGenerationAgent(self.llm, self.logger)

    def build_graph(self):
        """Build Enhanced Query Extraction graph with multi-agent architecture"""
        self.logger.info("Building Enhanced Query Extraction Multi-Agent graph")
        
        try:
            if self.memory is None:
                self.memory = MemorySaver()
            
            graph_builder = StateGraph(EnhancedText2SQLState, config_schema=SQLAgentConfiguration)
            
            # Add agents as nodes using their execute methods
            graph_builder.add_node("table_data_agent", self.table_data_agent.execute)
            graph_builder.add_node("context_analysis_agent", self.context_analysis_agent.execute)
            graph_builder.add_node("intent_analysis_agent", self.intent_analysis_agent.execute)
            graph_builder.add_node("sql_parameter_extraction_agent", self.sql_parameter_extraction_agent.execute)
            graph_builder.add_node("sql_generation_agent", self.sql_generation_agent.execute)
            
            # Define multi-agent workflow
            graph_builder.set_entry_point("table_data_agent")
            graph_builder.add_edge("table_data_agent", "context_analysis_agent")
            graph_builder.add_edge("context_analysis_agent", "intent_analysis_agent")
            graph_builder.add_edge("intent_analysis_agent", "sql_parameter_extraction_agent")
            graph_builder.add_edge("sql_parameter_extraction_agent", "sql_generation_agent")
            graph_builder.set_finish_point("sql_generation_agent")
            
            # Compile multi-agent graph
            compiled_graph = graph_builder.compile(
                checkpointer=self.memory,
                name="enhanced_query_extraction_multi_agent_graph" 
            )
            
            self.logger.info("Enhanced Query Extraction Multi-Agent graph compiled successfully")
            return compiled_graph
            
        except Exception as e:
            self.logger.error("Failed to build Enhanced Query Extraction Multi-Agent graph", error=str(e))
            raise
    
    def invoke(self, config: Dict = None) -> Dict:
        """Main entry point for enhanced query extraction multi-agent workflow"""
        try:
            if not hasattr(self, '_compiled_graph'):
                self._compiled_graph = self.build_graph()
            
            if config is None:
                config = {}
            
            if "configurable" not in config:
                config["configurable"] = {}
            if "thread_id" not in config["configurable"]:
                config["configurable"]["thread_id"] = "enhanced_extraction_multi_agent_session"
            
            initial_state = {
                "agent_results": {},
                "current_agent": None
            }
            
            result_state = self._compiled_graph.invoke(initial_state, config)
            
            return {
                "success": "errors" not in result_state or not result_state.get("errors", {}).get("error_message"),
                "table_info": result_state.get("table_info", {}),
                "intent_analysis": result_state.get("intent_analysis", {}),
                "context_analysis": result_state.get("context_analysis", {}),
                "sql_parameters": result_state.get("sql_parameters", {}),
                "message": result_state.get("analysis_result", "Multi-agent işlem tamamlandı."),
                "errors": result_state.get("errors", {}),
                "agent_results": result_state.get("agent_results", {}),
                "workflow_summary": {
                    "agents_executed": len(result_state.get("agent_results", {})),
                    "current_agent": result_state.get("current_agent"),
                    "total_messages": len(result_state.get("messages", []))
                }
            }
            
        except Exception as e:
            self.logger.error("Enhanced Query Extraction Multi-Agent workflow failed", error=str(e))
            return {
                "success": False,
                "table_info": {},
                "intent_analysis": {},
                "context_analysis": {},
                "sql_parameters": {},
                "message": f"Multi-agent sistem hatası: {str(e)}",
                "errors": {"error_message": str(e)},
                "agent_results": {},
                "workflow_summary": {
                    "agents_executed": 0,
                    "current_agent": None,
                    "total_messages": 0
                }
            }