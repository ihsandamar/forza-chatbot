# src/graphs/generic_sql_graph.py
"""
Generic SQL Graph - Configurable ERP Assistant using Text2SQL as subgraph
Bu graph text2sql_graph'ı subgraph olarak kullanarak configurable assistant oluşturur
"""

import os
import re
from typing import TypedDict, Annotated, List, Optional, Dict, Any, Literal
from datetime import datetime
from dataclasses import dataclass

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_community.utilities import SQLDatabase
from langchain_community.tools.sql_database.tool import QuerySQLDatabaseTool
from pydantic import BaseModel, Field

from src.graphs.base_graph import BaseGraph
from src.graphs.registry import register_graph
from src.graphs.text2sql_graph import Table
from src.graphs.core_text2sql_graph import CoreText2SQLGraph
from src.models.models import LLM, State
from src.models.base_assistant_configuration import BaseAssistantConfiguration
from src.services.app_logger import log
from src.services.config_loader import ConfigLoader

# ================================
# CONFIGURATION MODEL
# ================================

class SQLAgentConfiguration(BaseAssistantConfiguration):
    """Configurable parameters for Generic SQL Agent"""
    
    # Core Assistant Settings
    system_prompt: str = Field(
        default="Sen bir ERP uzmanı ve SQL sorgulama asistanısın. Görevin verilen bilgileri kullanarak senden istenilen sorguyu ve bilgiyi vermen.",
        description="Ana sistem promptu - assistant'ın rolünü ve davranışını belirler"
    )
    
    assistant_name: str = Field(
        default="ERP SQL Assistant",
        description="Assistant'ın adı"
    )
    
    # Database Configuration
    initial_setup_sql: str = Field(
        default="SELECT 1 as test_connection",
        description="Graph başlamadan önce çalıştırılacak setup SQL (temp table oluşturma vs.)"
    )

    table_name: str = Field(
        default="",
        description="Sorgu oluşturulacak ve çekilecek ana tablo adı"
    )

    table_columns: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Tablo kolonları bilgileri [{'name': 'kolon_adi', 'type': 'veri_tipi', 'description': 'açıklama'}]"
    )
    
    table_description: str = Field(
        default="Genel ERP tabloları",
        description="Kullanılacak tablonun açıklaması ve yapısı gibi ek detaylar"
    )
    
    cleanup_sql: str = Field(
        default="-- No cleanup needed",
        description="Graph sonunda çalıştırılacak temizlik SQL (temp table silme vs.)"
    )
    
    # Response Configuration
    response_template: str = Field(
        default="""Sen yardımcı bir müşteri hizmetleri asistanısın.

SQL sonucunu kullanıcı dostu bir şekilde açıkla.

Kullanıcı Sorusu: {question}
SQL Sorgusu: {query}  
SQL Sonucu: {result}

Kurallar:
- Emoji kullan ([CHART], [MONEY], [GROWTH], [OK], [STORE])
- Sayıları formatla
- Önemli bilgileri vurgula
- Kısa ve net ol
- Türkçe yanıt ver

Formatlanmış yanıt:""",
        description="Final yanıt template'i"
    )
    
    # Security and Performance Settings
    max_result_rows: int = Field(
        default=100,
        description="Maximum döndürülecek satır sayısı"
    )
    
    # Query Configuration
    allow_dangerous_queries: bool = Field(
        default=False,
        description="Tehlikeli SQL sorgularına izin ver"
    )
    
    query_timeout_seconds: int = Field(
        default=30,
        description="SQL sorgu timeout süresi (saniye)"
    )
    
    allowed_operations: List[str] = Field(
        default=["SELECT"],
        description="İzin verilen SQL operasyonları"
    )
    
    enable_query_fixing: bool = Field(
        default=True,
        description="SQL hata düzeltme özelliğini etkinleştir"
    )
    
    # Language Model Settings
    model: Annotated[
        Literal[
            "gpt-4o-mini",
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-3.5-turbo"
        ],
        {"__template_metadata__": {"kind": "llm"}},
    ] = Field(
        default="gpt-4o-mini",
        description="Kullanılacak language model"
    )
    
    temperature: float = Field(
        default=0.0,
        description="Model temperature ayarı"
    )
    
    # Data Exploration Settings
    max_distinct_values: int = Field(
        default=20,
        description="Her kolon için maksimum distinct değer sayısı"
    )

# ================================
# STATE DEFINITION
# ================================

# Using the same State as text2sql_graph for compatibility
# No need to redefine state - we'll use the existing State from models

# ================================
# CORE FUNCTIONS
# ================================

def prepare_table_data(state: State, config: RunnableConfig, db: SQLDatabase) -> State:
    """Prepare table data with distinct values for text2sql subgraph"""
    logger = log.get(module="generic_sql", function="prepare_table_data")
    
    try:
        # Get configuration
        configurable = config.get("configurable", {})
        assistant_config = configurable.get("assistant_config", {})
        table_name = assistant_config.get("table_name", "")
        table_columns = assistant_config.get("table_columns", [])
        table_description = assistant_config.get("table_description", "")
        max_distinct_values = assistant_config.get("max_distinct_values", 20)
        
        if not table_name:
            logger.error("No table name provided in configuration")
            state["is_error"] = True
            state["error_message"] = "Table name is required"
            return state
        
        # Create Table object with distinct values
        table = Table(
            name=table_name,
            columns=[],
            relations=[],
            schema="",
            distinct_values={}
        )
        
        # Collect distinct values for each column
        execute_tool = QuerySQLDatabaseTool(db=db)
        
        for column in table_columns:
            column_name = column.get("name", "")
            column_type = column.get("type", "").lower()
            column_desc = column.get("description", "")
            
            if not column_name:
                continue
            
            # Add column info
            table.columns.append(f"[{column_name}] ({column_type}): {column_desc}")
            
            try:
                # Skip certain data types that might have too many distinct values
                if any(skip_type in column_type for skip_type in ['text', 'ntext', 'image', 'binary']):
                    logger.info(f"Skipping distinct values for column {column_name} due to data type: {column_type}")
                    continue
                
                # Get distinct values
                distinct_query = f"""
                SELECT DISTINCT TOP {max_distinct_values} [{column_name}]
                FROM [{table_name}]
                WHERE [{column_name}] IS NOT NULL
                ORDER BY [{column_name}]
                """
                
                result = execute_tool.invoke(distinct_query)
                
                if result:
                    # Parse result into list of values
                    result_str = str(result).strip()
                    values = []
                    
                    if result_str and result_str != "[]":
                        # Split by newlines and clean up
                        lines = result_str.split('\n')
                        for line in lines:
                            line = line.strip()
                            if line and not line.startswith('(') and line != '[]':
                                # Remove parentheses and quotes
                                clean_value = line.strip("(),'\"")
                                if clean_value and clean_value not in ['None', 'NULL']:
                                    values.append(clean_value)
                    
                    # Limit values
                    if len(values) > max_distinct_values:
                        values = values[:max_distinct_values]
                    
                    table.distinct_values[column_name] = values
                    logger.info(f"Collected {len(values)} distinct values for column {column_name}")
                
            except Exception as col_error:
                logger.warning(f"Failed to get distinct values for column {column_name}", error=str(col_error))
                table.distinct_values[column_name] = []
        
        # Add table description
        if table_description:
            table.schema = f"-- Table Description: {table_description}"
        
        # Set up state for text2sql subgraph
        state["relevant_tables"] = [table]
        state["table_schemas"] = table.schema
        state["all_tables"] = [table_name]
        
        logger.info("Table data prepared successfully", 
                   table_name=table_name,
                   columns_count=len(table.columns),
                   distinct_values_count=len(table.distinct_values))
        
    except Exception as e:
        logger.error("Failed to prepare table data", error=str(e))
        state["is_error"] = True
        state["error_message"] = f"Table preparation error: {str(e)}"
    
    return state


def format_response(state: State, config: RunnableConfig, llm: LLM) -> State:
    """Format the final response using the configured template"""
    logger = log.get(module="generic_sql", function="format_response")
    
    try:
        # Get configuration
        configurable = config.get("configurable", {})
        assistant_config = configurable.get("assistant_config", {})
        response_template = assistant_config.get("response_template", DEFAULT_RESPONSE_TEMPLATE)
        assistant_name = assistant_config.get("assistant_name", "SQL Assistant")
        
        # Get data from state
        user_query = state.get("user_query", "")
        sql_result = state.get("sql_result", "")
        validated_sql = state.get("validated_sql", "")
        
        # Handle error cases
        if state.get("is_error", False):
            error_message = state.get("error_message", "Unknown error")
            formatted_answer = f"""
[ERROR] **{assistant_name} - İşlem Başarısız**

**Sorunuz:** {user_query}
**Hata:** {error_message}

🔄 **Öneriler:**
• Sorunuzu daha basit ifade edin
• Tablo ve sütun adlarını kontrol edin
• Tarih formatlarını doğru kullanın

📞 Yardım için destek ekibi ile iletişime geçebilirsiniz.
"""
        else:
            # Create formatted response using template
            prompt = ChatPromptTemplate.from_messages([
                ("system", response_template),
                ("human", "Yanıtı oluştur")
            ])
            
            message = prompt.invoke({
                "question": user_query,
                "query": validated_sql,
                "result": sql_result
            })
            
            response = llm.get_chat().invoke(message)
            formatted_answer = response.content
            
            # Add metadata footer
            current_time = datetime.now().strftime("%H:%M")
            footer = f"\n\n---\n📌 **{assistant_name} Bilgi**\n• Zaman: {current_time}"
            formatted_answer += footer
        
        # Add formatted response to messages
        if "messages" not in state:
            state["messages"] = []
        
        from langchain.schema import AIMessage
        ai_message = AIMessage(content=formatted_answer)
        state["messages"].append(ai_message)
        
        logger.info("Response formatted successfully", response_length=len(formatted_answer))
        
    except Exception as e:
        logger.error("Response formatting failed", error=str(e))
        # Fallback response
        if "messages" not in state:
            state["messages"] = []
        from langchain.schema import AIMessage
        fallback_message = AIMessage(content=f"Yanıt oluşturulamadı: {str(e)}")
        state["messages"].append(fallback_message)
    
    return state


# Default response template
DEFAULT_RESPONSE_TEMPLATE = """Sen yardımcı bir müşteri hizmetleri asistanısın.

SQL sonucunu kullanıcı dostu bir şekilde açıkla.

Kullanıcı Sorusu: {question}
SQL Sorgusu: {query}
SQL Sonucu: {result}

Kurallar:
- Emoji kullan ([CHART], [MONEY], [GROWTH], [OK], [STORE])
- Sayıları formatla
- Önemli bilgileri vurgula
- Kısa ve net ol
- Türkçe yanıt ver

Formatlanmış yanıt:"""


# ================================
# MAIN GRAPH CLASS
# ================================

@register_graph("generic_sql")
class GenericSQLGraph(BaseGraph):
    """Generic SQL Graph using Text2SQL as subgraph"""
    
    def __init__(self, llm: LLM, db: SQLDatabase = None, memory: MemorySaver = None):
        super().__init__(llm=llm, state_class=State, memory=memory)
        self.logger = log.get(module="generic_sql_graph")
        
        # Database setup
        if db is None:
            config = ConfigLoader.load_config("config/text2sql_config.yaml")
            db = SQLDatabase.from_uri(config.database.uri)
        
        self.db = db
        
        # Initialize Core Text2SQL subgraph
        self.core_text2sql_graph = CoreText2SQLGraph(llm=llm, db=db, memory=memory)
        
        self.logger.info("Generic SQL Graph initialized with Core Text2SQL subgraph")
    
    def build_graph(self):
        """Build the generic SQL graph using Core Text2SQL as subgraph"""
        self.logger.info("Building generic SQL graph with Core Text2SQL subgraph")
        
        try:
            # Create memory if not provided
            if self.memory is None:
                self.memory = MemorySaver()
            
            # Create state graph with configuration schema
            graph_builder = StateGraph(State, config_schema=SQLAgentConfiguration)
            
            # Node wrapper functions
            def prepare_data_node(state: State, *, config: RunnableConfig) -> State:
                return prepare_table_data(state, config, self.db)
            
            def format_response_node(state: State, *, config: RunnableConfig) -> State:
                return format_response(state, config, self.llm)
            
            # Build the core text2sql subgraph
            core_text2sql_compiled = self.core_text2sql_graph.build_graph()
            
            # Add nodes to graph
            graph_builder.add_node("prepare_data", prepare_data_node)
            # Add Core Text2SQL as subgraph
            graph_builder.add_node("core_text2sql_subgraph", core_text2sql_compiled)
            graph_builder.add_node("format_response", format_response_node)
            
            # Define simple flow
            graph_builder.add_edge(START, "prepare_data")
            graph_builder.add_edge("prepare_data", "core_text2sql_subgraph")
            graph_builder.add_edge("core_text2sql_subgraph", "format_response")
            graph_builder.add_edge("format_response", END)
            
            # Compile graph
            compiled_graph = graph_builder.compile(
                checkpointer=self.memory,
                name="generic_sql_graph"
            )
            
            self.logger.info("Generic SQL graph compiled successfully with Core Text2SQL subgraph")
            return compiled_graph
            
        except Exception as e:
            self.logger.error("Failed to build generic SQL graph", error=str(e))
            raise
    
    def invoke(self, messages: List[Any], config: Optional[Dict] = None) -> str:
        """Main entry point - compatible with existing chatbot interface"""
        try:
            # Extract question from messages
            question = self._extract_question(messages)
            
            if not question:
                return self._create_help_message()
            
            # Create initial state
            initial_state = {
                "messages": messages if isinstance(messages, list) else [],
                "user_query": question,
                "all_tables": [],
                "relevant_tables": [],
                "table_schemas": "",
                "query_parameters": None,
                "generated_sql": "",
                "validated_sql": "",
                "is_valid": False,
                "sql_result": "",
                "is_error": False,
                "error_message": "",
                "fixed_sql": ""
            }
            
            # Build graph if needed
            if not hasattr(self, '_compiled_graph'):
                self._compiled_graph = self.build_graph()
            
            # Default config
            if config is None:
                config = {"configurable": {"thread_id": "default"}}
            
            # Run the graph
            result = self._compiled_graph.invoke(initial_state, config)
            
            # Extract final message from state
            if result.get("messages") and len(result["messages"]) > 0:
                final_message = result["messages"][-1]
                if hasattr(final_message, 'content'):
                    return final_message.content
                elif isinstance(final_message, dict):
                    return final_message.get("content", "Yanıt oluşturulamadı")
            
            return "Yanıt oluşturulamadı"
            
        except Exception as e:
            self.logger.error("Processing failed", error=str(e))
            return self._create_error_message(str(e))
    
    def _extract_question(self, messages: List[Any]) -> str:
        """Extract question from various message formats"""
        if isinstance(messages, list):
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    return msg.get("content", "")
                elif isinstance(msg, HumanMessage):
                    return msg.content
                elif hasattr(msg, "type") and msg.type == "human":
                    return msg.content if hasattr(msg, "content") else ""
        
        return ""
    
    def _create_help_message(self) -> str:
        """Create help message"""
        return """
[ROBOT] **Generic SQL Assistant**

Size nasıl yardımcı olabilirim?

Bu assistant tamamen konfigüre edilebilir ve Core Text2SQL teknolojisi kullanır.

[NOTE] Sorularınızı yazın ve size SQL tabanlı yanıtlar sunayım.

💡 **İpucu:** Spesifik veriler, raporlar, analizler hakkında sorular sorabilirsiniz.
"""
    
    def _create_error_message(self, error: str) -> str:
        """Create error message"""
        return f"""
[ERROR] **Sistem Hatası**

Üzgünüm, bir hata oluştu:
{error}

🔄 Lütfen tekrar deneyin veya sorunuzu basitleştirin.
"""


# ================================
# EXAMPLE CONFIGURATIONS
# ================================

def get_example_config():
    """Example configuration for generic SQL graph"""
    return {
        "system_prompt": "Sen bir ERP uzmanı ve SQL sorgulama asistanısın. Görevin verilen bilgileri kullanarak senden istenilen sorguyu ve bilgiyi vermen.",
        "assistant_name": "ERP SQL Assistant",
        "table_name": "Products",
        "table_columns": [
            {
                "name": "ProductID",
                "type": "int",
                "description": "Ürün benzersiz kimliği"
            },
            {
                "name": "ProductName", 
                "type": "nvarchar(100)",
                "description": "Ürün adı"
            },
            {
                "name": "Price",
                "type": "decimal(10,2)", 
                "description": "Ürün fiyatı"
            }
        ],
        "table_description": "Ürün bilgilerinin tutulduğu ana tablo",
        "max_distinct_values": 20,
        "response_template": DEFAULT_RESPONSE_TEMPLATE
    }


if __name__ == "__main__":
    """Example usage"""
    from src.models.models import LLM
    
    # Initialize LLM
    llm = LLM(model="gpt-4o-mini", temperature=0.0)
    
    # Create graph
    graph = GenericSQLGraph(llm)
    
    # Example messages
    messages = [
        HumanMessage(content="Ürünlerin fiyatlarını göster")
    ]
    
    # Example config
    config = {"configurable": get_example_config()}
    
    # Run
    response = graph.invoke(messages, config)
    print("[ROCKET] Generic SQL Graph Response:")
    print(response)