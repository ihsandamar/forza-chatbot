"""
Utility functions for Enhanced Query Extraction Graph
"""
import re
from typing import List, Dict, Any, Optional
from langchain_core.messages import AnyMessage


def extract_plain_text_from_message(content) -> str:
    """Extract plain text from various message content formats"""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif hasattr(item, 'text'):
                text_parts.append(item.text)
            elif isinstance(item, dict) and 'text' in item:
                text_parts.append(item['text'])
            else:
                text_parts.append(str(item))
        return ' '.join(text_parts)
    else:
        return str(content)


def estimate_tokens(text: str) -> int:
    """Estimate token count for text (rough approximation)"""
    return max(1, len(text) // 4)


def extract_key_entities(messages: List[AnyMessage]) -> List[str]:
    """Extract key entities from message history"""
    entities = set()
    for msg in messages:
        content = msg.content
        if isinstance(content, list):
            content = ' '.join(str(item) for item in content)
        content = str(content).upper()
        words = content.split()
        for word in words:
            if len(word) > 2 and (word.isupper() or word.isdigit()):
                entities.add(word)
    return list(entities)[:5]


def extract_topics(messages: List[AnyMessage]) -> List[str]:
    """Extract business topics from messages"""
    topics = set()
    business_keywords = [
        'satış', 'müşteri', 'ürün', 'fatura', 'sipariş', 'stok', 
        'personel', 'departman', 'gelir', 'gider', 'kar', 'zarar'
    ]
    for msg in messages:
        content = msg.content
        if isinstance(content, list):
            content = ' '.join(str(item) for item in content)
        content = str(content).lower()
        for keyword in business_keywords:
            if keyword in content:
                topics.add(keyword)
    return list(topics)[:3]


def detect_sql_result_patterns(messages: List[AnyMessage]) -> bool:
    """Detect if previous messages contain SQL query results"""
    sql_result_patterns = [
        r'(SELECT|FROM|WHERE|JOIN|GROUP BY)',
        r'(\d+\s+(rows?|sonuç|kayıt))',
        r'(toplam|sum|count|ortalama|average)',
        r'(tablo|table|column|kolon)',
        r'(SQL|query|sorgu)',
    ]
    
    for msg in messages[-5:]:
        if hasattr(msg, 'type') and msg.type == 'tool':
            # Check for tool messages with SQL results
            content = str(msg.content).lower()
            if any(re.search(pattern, content, re.IGNORECASE) for pattern in sql_result_patterns):
                return True
                
        # Check regular messages for SQL-like content
        content = str(msg.content).lower()
        if any(re.search(pattern, content, re.IGNORECASE) for pattern in sql_result_patterns):
            return True
    
    return False


def validate_sql_query(sql_query: str) -> Dict[str, Any]:
    """Validate basic SQL query structure"""
    validation_result = {
        "is_valid": False,
        "has_select": False,
        "has_from": False,
        "has_where": False,
        "has_aggregation": False,
        "warnings": []
    }
    
    if not sql_query or not isinstance(sql_query, str):
        validation_result["warnings"].append("Empty or invalid SQL query")
        return validation_result
    
    sql_upper = sql_query.upper()
    
    # Check basic structure
    validation_result["has_select"] = "SELECT" in sql_upper
    validation_result["has_from"] = "FROM" in sql_upper
    validation_result["has_where"] = "WHERE" in sql_upper
    validation_result["has_aggregation"] = any(agg in sql_upper for agg in ["SUM", "COUNT", "AVG", "MAX", "MIN"])
    
    # Basic validity check
    validation_result["is_valid"] = validation_result["has_select"] and validation_result["has_from"]
    
    # Add warnings
    if not validation_result["has_select"]:
        validation_result["warnings"].append("Missing SELECT clause")
    if not validation_result["has_from"]:
        validation_result["warnings"].append("Missing FROM clause")
    
    return validation_result


def format_agent_results(agent_results: Dict[str, Any]) -> str:
    """Format agent execution results for display"""
    if not agent_results:
        return "No agent results available"
    
    formatted_results = []
    
    for agent_name, result in agent_results.items():
        status = result.get("status", "unknown")
        execution_time = result.get("execution_time", 0)
        
        if status == "success":
            status_icon = "[OK]"
        elif status == "error":
            status_icon = "[ERROR]"
        else:
            status_icon = "[WARNING]"
        
        agent_display = f"{status_icon} **{agent_name.replace('_', ' ').title()}** - {status}"
        
        if status == "error" and "error" in result:
            agent_display += f"\n   Error: {result['error']}"
        
        formatted_results.append(agent_display)
    
    return "\n".join(formatted_results)


def clean_sql_query(sql_query: str) -> str:
    """Clean and format SQL query"""
    if not sql_query:
        return ""
    
    # Remove comments
    sql_query = re.sub(r'--.*?\n', '', sql_query)
    
    # Remove extra whitespace
    sql_query = ' '.join(sql_query.split())
    
    # Ensure proper semicolon ending
    sql_query = sql_query.rstrip(';') + ';'
    
    return sql_query


def extract_column_names_from_table(table_info: Dict[str, Any]) -> List[str]:
    """Extract all column names from table info"""
    if not table_info or "columns" not in table_info:
        return []
    
    return [col.get("name", "") for col in table_info["columns"] if col.get("name")]


def find_semantic_matches(user_term: str, distinct_values: List[str], threshold: float = 0.7) -> List[Dict[str, Any]]:
    """Find semantic matches for a user term in distinct values"""
    matches = []
    user_term_lower = user_term.lower()
    
    for value in distinct_values:
        value_lower = value.lower()
        
        # Direct substring match
        if user_term_lower in value_lower:
            matches.append({
                "value": value,
                "match_type": "direct",
                "confidence": 0.95
            })
        # Reverse substring match
        elif value_lower in user_term_lower:
            matches.append({
                "value": value,
                "match_type": "partial",
                "confidence": 0.80
            })
    
    # Sort by confidence
    matches.sort(key=lambda x: x["confidence"], reverse=True)
    return matches[:5]  # Top 5 matches