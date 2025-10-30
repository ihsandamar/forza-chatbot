"""
Tools for Enhanced Query Extraction Graph
"""
import re
from typing import Dict, Any, List, Optional
from langchain_core.tools import tool
from langchain_core.messages import AnyMessage
from src.config.business_terms_config import business_config


@tool
def distinct_value_replacement_tool(sql_query: str, value_matches: List[Dict], table_columns: List[Dict]) -> Dict:
    """Tool for replacing user terms with actual database distinct values in SQL query"""
    
    if not sql_query or not value_matches:
        return {
            "original_sql": sql_query,
            "modified_sql": sql_query,
            "replacements_made": [],
            "success": False,
            "message": "No SQL query or value matches provided"
        }
    
    try:
        modified_sql = sql_query
        replacements_made = []
        
        # Create mapping of distinct values for each column
        column_values_map = {}
        for col in table_columns:
            col_name = col.get("name", "")
            distinct_values = col.get("distinct_values", [])
            if col_name and distinct_values:
                column_values_map[col_name] = distinct_values
        
        # Process each value match
        for match in value_matches:
            user_term = match.get("user_term", "")
            matched_value = match.get("matched_value", match.get("value", ""))
            column = match.get("column", "")
            
            if not user_term or not matched_value or not column:
                continue
                
            # Replace in SQL query - handle various SQL patterns
            patterns_to_replace = [
                f"= '{user_term}'",
                f'= "{user_term}"',
                f"= {user_term}",
                f"LIKE '%{user_term}%'",
                f"LIKE '{user_term}%'",
                f"LIKE '%{user_term}'",
                f"IN ('{user_term}'",
                f'IN ("{user_term}"',
                user_term  # Direct replacement
            ]
            
            replacement_patterns = [
                f"= '{matched_value}'",
                f'= "{matched_value}"',
                f"= '{matched_value}'",  # Convert to string
                f"LIKE '%{matched_value}%'",
                f"LIKE '{matched_value}%'",
                f"LIKE '%{matched_value}'",
                f"IN ('{matched_value}'",
                f'IN ("{matched_value}"',
                matched_value  # Direct replacement
            ]
            
            # Try each pattern replacement
            for i, pattern in enumerate(patterns_to_replace):
                if pattern in modified_sql:
                    old_sql = modified_sql
                    modified_sql = modified_sql.replace(pattern, replacement_patterns[i])
                    if old_sql != modified_sql:
                        replacements_made.append({
                            "user_term": user_term,
                            "matched_value": matched_value,
                            "column": column,
                            "pattern_replaced": pattern,
                            "replacement": replacement_patterns[i]
                        })
                        break
        
        return {
            "original_sql": sql_query,
            "modified_sql": modified_sql,
            "replacements_made": replacements_made,
            "replacements_count": len(replacements_made),
            "success": True,
            "message": f"Successfully processed {len(replacements_made)} replacements"
        }
        
    except Exception as e:
        return {
            "original_sql": sql_query,
            "modified_sql": sql_query,
            "replacements_made": [],
            "success": False,
            "message": f"Error during replacement: {str(e)}"
        }


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
        }
        
        # AI-powered previous SQL results detection
        def detect_previous_sql_results(messages: List[AnyMessage]) -> bool:
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
        
        flow_indicators["has_previous_results"] = detect_previous_sql_results(msgs)
        
        return flow_indicators

    def extract_plain_text_from_message(content):
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

    def build_context_result(messages: List[AnyMessage], max_tokens: int, token_budget: int = 800) -> Dict:
        context_result = {
            "recent_context": [],
            "conversation_summary": "",
            "key_entities": [],
            "topics": [],
            "total_tokens": 0
        }
        
        if not messages:
            return context_result

        current_content = extract_plain_text_from_message(messages[-1].content)
        current_tokens = estimate_tokens(current_content)
        
        context_result["current_message"] = extract_plain_text_from_message(messages[-1].content)
        context_result["total_tokens"] += current_tokens

        recent_messages = []
        for msg in reversed(messages[:-1]):
            msg_content = extract_plain_text_from_message(msg.content)
            msg_tokens = estimate_tokens(msg_content)
            
            if context_result["total_tokens"] + msg_tokens > token_budget:
                break
                
            context_result["total_tokens"] += msg_tokens
            recent_messages.insert(0, msg_content[:300])

        context_result["recent_context"] = recent_messages

        # Conversation summary for older messages
        remaining_budget = max_tokens - context_result["total_tokens"]
        if remaining_budget > 100 and len(messages) > 5:
            entities = extract_key_entities(messages[:-5])
            topics = extract_topics(messages[:-5])
            context_result["key_entities"] = entities
            context_result["topics"] = topics
            summary = f"Önceki konuşma: {', '.join(topics)} konularında {', '.join(entities)} hakkında sorular."
            context_result["conversation_summary"] = summary[:200]
            context_result["total_tokens"] += estimate_tokens(summary)

        return context_result

    try:
        msgs = messages or []
        context_data = build_context_result(msgs, max_tokens)
        
        # Add flow analysis
        flow_data = detect_conversation_flow(msgs)
        context_data.update(flow_data)
        
        return context_data
        
    except Exception as e:
        return {
            "error": f"Context analysis failed: {str(e)}",
            "recent_context": [],
            "conversation_summary": "",
            "key_entities": [],
            "topics": [],
            "total_tokens": 0,
            "has_previous_results": False
        }


@tool
def prompt_builder_tool(context_data: Dict, table_info: Dict) -> str:
    """Build optimized prompt for SQL generation with context"""
    
    # Extract table information for context
    table_context = ""
    if table_info and table_info.get("columns"):
        searchable_columns = [
            col["name"] for col in table_info["columns"] 
            if col.get("distinct_values") or col.get("semantic_matches")
        ]
        table_context = f"Aranabilir kolonlar: {', '.join(searchable_columns[:10])}"
    
    # Build context sections
    recent_context = ""
    if context_data.get("recent_context"):
        recent_context = f"Son mesajlar: {' | '.join(context_data['recent_context'][-3:])}"
    
    conversation_summary = context_data.get("conversation_summary", "")
    
    # Flow indicators for conversation type detection
    flow_indicators = {
        "has_previous_results": context_data.get("has_previous_results", False),
        "pronoun_references": context_data.get("pronoun_references", []),
        "query_references": context_data.get("query_references", []),
    }
    
    current_message = context_data.get("current_message", "")
    
    prompt_template = f"""Sen bir SQL query analiz uzmanısın. Kullanıcı sorularını analiz et ve intent bilgilerini çıkar.

==== CONTEXT INFORMATION ====
{table_context}
{recent_context}
{conversation_summary}

==== CONVERSATION FLOW INDICATORS ====
Has Previous Results: {flow_indicators['has_previous_results']}
Pronoun References: {flow_indicators['pronoun_references']}
Query References: {flow_indicators['query_references']}

==== CURRENT USER QUERY ====
{current_message}

==== CONVERSATION TYPE DETECTION ====
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

==== OUTPUT FORMAT ====
JSON formatında döndür:
{{
    "conversation_type": "new_query/follow_up/drill_down/refinement/clarification/comparison_extension",
    "confidence": 0.0-1.0,
    "intent_category": "data_retrieval/aggregation/comparison/trend/filtering",
    "key_entities": ["varlık1", "varlık2"],
    "filters": [],
    "aggregations": [],
    "columns": [],
    "context_usage": "none/partial/heavy",
    "reasoning": "Kısa açıklama"
}}"""

    return prompt_template


@tool 
def response_parser_tool(llm_response: str, context_data: Dict) -> Dict:
    """Parse LLM response and extract structured data"""
    try:
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON found in response")
            
        import json
        parsed_data = json.loads(json_match.group())
        
        # Validate required fields
        required_fields = ['conversation_type', 'confidence', 'intent_category']
        for field in required_fields:
            if field not in parsed_data:
                parsed_data[field] = 'unknown'
                
        # Set defaults for optional fields
        optional_defaults = {
            'key_entities': [],
            'filters': [],
            'aggregations': [],
            'columns': [],
            'context_usage': 'none',
            'reasoning': 'No reasoning provided'
        }
        
        for field, default in optional_defaults.items():
            if field not in parsed_data:
                parsed_data[field] = default
                
        return {
            "parsed_response": parsed_data,
            "raw_response": llm_response,
            "success": True
        }
        
    except Exception as e:
        # Fallback parsing
        fallback_result = {
            "conversation_type": "new_query",
            "confidence": 0.5,
            "intent_category": "data_retrieval",
            "key_entities": [],
            "filters": [],
            "aggregations": [],
            "columns": [],
            "context_usage": "none",
            "reasoning": f"Parsing failed: {str(e)}"
        }
        
        return {
            "parsed_response": fallback_result,
            "raw_response": llm_response,
            "success": False,
            "error": str(e)
        }


@tool
def table_data_extraction_tool(table_name: str, table_columns: List[Dict], max_distinct_values: int, db_connection: Any) -> Dict:
    """Extract table schema with distinct values for semantic matching"""
    
    def semantic_entity_matching(distinct_values: List[str], user_terms: List[str]) -> Dict:
        """Enhanced semantic matching for business entities"""
        matches = {}
        for user_term in user_terms:
            user_term_lower = user_term.lower()
            best_matches = []
            
            for value in distinct_values:
                value_lower = value.lower()
                
                # Direct substring match
                if user_term_lower in value_lower:
                    best_matches.append({
                        "value": value,
                        "match_type": "direct",
                        "confidence": 0.95
                    })
                # Fuzzy match for common business terms
                elif user_term_lower in ['doğalgaz', 'dogalgaz', 'dogalgz'] and any(fuzzy in value_lower for fuzzy in ['dogalgaz', 'doğalgaz', 'gaz']):
                    best_matches.append({
                        "value": value,
                        "match_type": "fuzzy",
                        "confidence": 0.85
                    })
            
            if best_matches:
                matches[user_term] = best_matches[:5]
        
        return matches

    def should_extract_distinct_values(column_type: str) -> bool:
        """
        Check if distinct values should be extracted for this column type.
        Exclude GUID and numeric types, include all others.
        """
        col_type_lower = column_type.lower()
        
        # Exclude GUID types
        guid_types = ['uniqueidentifier', 'guid', 'uuid']
        if any(guid_type in col_type_lower for guid_type in guid_types):
            return False
            
        # Exclude numeric types
        numeric_types = ['int', 'bigint', 'smallint', 'tinyint', 'decimal', 'numeric', 'float', 'real', 'money', 'smallmoney']
        if any(numeric_type in col_type_lower for numeric_type in numeric_types):
            return False
            
        # Include all other types (varchar, nvarchar, char, text, datetime, bit, etc.)
        return True

    try:
        enriched_columns = []
        
        for config_col in table_columns:
            col_name = config_col.get("name", "")
            # Support both 'data_type' and 'type' field names for config compatibility
            col_type = config_col.get("data_type") or config_col.get("type", "")
            col_nullable = config_col.get("nullable", True)
            col_primary_key = config_col.get("primary_key", False)
            col_description = config_col.get("description", "")
            
            column_info = {
                "name": col_name,
                "data_type": col_type,
                "nullable": col_nullable,
                "primary_key": col_primary_key,
                "description": col_description,
                "distinct_values": [],
                "semantic_matches": {}
            }
            
            # Extract distinct values for all columns except GUID and numeric types
            if col_name and should_extract_distinct_values(col_type):
                try:
                    query = f"SELECT DISTINCT TOP {max_distinct_values} [{col_name}] FROM [{table_name}] WHERE [{col_name}] IS NOT NULL"
                    print(f"[DEBUG] Executing query for column {col_name} ({col_type}): {query}")
                    result = db_connection.run(query)
                    print(f"[DEBUG] Query result for {col_name} ({col_type}): {result[:200]}..." if result else "[DEBUG] No result")
                    
                    values = []
                    if result:
                        if isinstance(result, str):
                            # Handle string result format
                            result_str = result.strip()
                            
                            # Check if it looks like a list of tuples: "[('value1',), ('value2',)]"
                            if result_str.startswith('[') and result_str.endswith(']') and '(' in result_str:
                                # Special handling for datetime results that can't be parsed by AST
                                if 'datetime.datetime(' in result_str:
                                    import re
                                    # Extract datetime patterns: datetime.datetime(2025, 7, 28, 14, 25, 19)
                                    datetime_pattern = r'datetime\.datetime\((\d+),\s*(\d+),\s*(\d+)(?:,\s*(\d+))?(?:,\s*(\d+))?(?:,\s*(\d+))?\)'
                                    matches = re.findall(datetime_pattern, result_str)
                                    for match in matches:
                                        year, month, day, hour, minute, second = match
                                        hour = hour or '0'
                                        minute = minute or '0'  
                                        second = second or '0'
                                        # Format as readable datetime string
                                        datetime_str = f"{year}-{month.zfill(2)}-{day.zfill(2)} {hour.zfill(2)}:{minute.zfill(2)}:{second.zfill(2)}"
                                        values.append(datetime_str)
                                else:
                                    # Standard AST parsing for regular values
                                    try:
                                        import ast
                                        parsed_result = ast.literal_eval(result_str)
                                        if isinstance(parsed_result, list):
                                            for item in parsed_result:
                                                if isinstance(item, tuple) and len(item) > 0:
                                                    raw_value = item[0]
                                                    if raw_value is not None:
                                                        # Format datetime objects properly
                                                        if hasattr(raw_value, 'strftime'):  # datetime object
                                                            value = raw_value.strftime('%Y-%m-%d %H:%M:%S')
                                                        else:
                                                            value = str(raw_value).strip()
                                                        if value:
                                                            values.append(value)
                                    except (ValueError, SyntaxError):
                                        # Fall back to line-by-line parsing
                                        for line in result_str.split('\n'):
                                            line = line.strip()
                                            if line and line != col_name and not line.startswith('-') and not line.startswith('('):
                                                values.append(line)
                            else:
                                # Legacy/text format with newlines
                                for line in result_str.split('\n'):
                                    line = line.strip()
                                    if line and line != col_name and not line.startswith('-') and not line.startswith('('):
                                        values.append(line)
                        elif isinstance(result, list):
                            # Handle list of tuples result format (modern/structured format)
                            for row in result:
                                if isinstance(row, tuple) and len(row) > 0:
                                    # Handle different data types within tuples
                                    raw_value = row[0]
                                    if raw_value is not None:
                                        # Format datetime objects properly
                                        if hasattr(raw_value, 'strftime'):  # datetime object
                                            value = raw_value.strftime('%Y-%m-%d %H:%M:%S')
                                        else:
                                            value = str(raw_value).strip()
                                        if value:
                                            values.append(value)
                                elif isinstance(row, (str, int, float)):
                                    # Handle simple values
                                    value = str(row).strip()
                                    if value:
                                        values.append(value)
                        else:
                            # Handle other result formats - try to convert to string and parse
                            str_result = str(result)
                            if str_result and str_result != "None":
                                # Parse structured data like "[('Monday',), ('Saturday',)]"
                                import ast
                                try:
                                    parsed_result = ast.literal_eval(str_result)
                                    if isinstance(parsed_result, list):
                                        for item in parsed_result:
                                            if isinstance(item, tuple) and len(item) > 0:
                                                raw_value = item[0]
                                                if raw_value is not None:
                                                    # Format datetime objects properly
                                                    if hasattr(raw_value, 'strftime'):  # datetime object
                                                        value = raw_value.strftime('%Y-%m-%d %H:%M:%S')
                                                    else:
                                                        value = str(raw_value).strip()
                                                    if value:
                                                        values.append(value)
                                except (ValueError, SyntaxError):
                                    # If parsing fails, treat as a single string value
                                    values.append(str_result.strip())
                    
                    column_info["distinct_values"] = values[:max_distinct_values]
                    print(f"[DEBUG] Column {col_name} ({col_type}) extracted {len(values)} distinct values: {values[:3]}...")
                    
                    # Add semantic matching for common business terms from config
                    common_terms = business_config.get_common_terms()
                    if values:
                        column_info["semantic_matches"] = semantic_entity_matching(values, common_terms)
                        
                except Exception as e:
                    print(f"[DEBUG] Error extracting distinct values for column {col_name} ({col_type}): {e}")
                    column_info["distinct_values"] = []
                    column_info["semantic_matches"] = {}
            else:
                # GUID/numeric columns: skip distinct value extraction to save tokens
                print(f"[DEBUG] Skipping GUID/numeric column {col_name} ({col_type}) - no distinct values extracted")
                column_info["distinct_values"] = []
                column_info["semantic_matches"] = {}
            
            enriched_columns.append(column_info)
        
        return {
            "table_name": table_name,
            "columns": enriched_columns,
            "relations": [],
            "semantic_matching_enabled": True
        }
        
    except Exception as e:
        raise Exception(f"Table data extraction failed: {str(e)}")