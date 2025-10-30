"""
Enhanced Query Extraction Graph - Main Graph Implementation
Multi-Agent Architecture for SQL Query Generation
"""
import time
from typing import Dict, Any
from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langchain_community.utilities import SQLDatabase

from src.graphs.base_graph import BaseGraph
from src.graphs.registry import register_graph
from src.services.app_logger import log
from src.graphs.generic_sql_graph import SQLAgentConfiguration
from src.services.config_loader import ConfigLoader

from .enhanced_query_extraction.models import EnhancedText2SQLState
from .enhanced_query_extraction.agents import (
    TableDataAgent,
    ContextAnalysisAgent, 
    IntentAnalysisAgent,
    QueryEnhancementAgent,
    SQLGenerationAgent,
    SQLExecutionAgent
)

config = ConfigLoader.load_config("config/config.yaml")

@register_graph("enhanced_query_extraction")
class EnhancedQueryExtractionGraph(BaseGraph):
    """Enhanced Query Extraction Graph - Multi-Agent Architecture with specialized agents, tools, and graph orchestration"""
    
    def __init__(self, llm, db: SQLDatabase = None, memory: MemorySaver = None, assistant_configuration=None):
        super().__init__(llm=llm, state_class=EnhancedText2SQLState, memory=memory)
        self.logger = log.get(module="enhanced_query_extraction_graph")
        self.db = db if db is not None else SQLDatabase.from_uri(config.database.uri)
        self.assistant_configuration = assistant_configuration
        self._initialize_agents()
        self.logger.info("Enhanced Query Extraction Multi-Agent Graph initialized")

    def _initialize_agents(self):
        """Initialize specialized agents"""
        self.table_data_agent = TableDataAgent(self.db, self.logger)
        self.context_analysis_agent = ContextAnalysisAgent(self.logger)
        self.intent_analysis_agent = IntentAnalysisAgent(self.llm, self.logger, self.assistant_configuration)
        self.query_enhancement_agent = QueryEnhancementAgent(self.llm, self.db, self.logger, self.assistant_configuration)
        self.sql_generation_agent = SQLGenerationAgent(self.llm, self.logger, self.assistant_configuration)
        self.sql_execution_agent = SQLExecutionAgent(self.db, self.logger)

    def _cleanup_state(self, state: EnhancedText2SQLState, *, config) -> EnhancedText2SQLState:
        """Clean state completely but preserve messages - ensures fresh start for new queries"""
        messages = state.get("messages", [])
        
        # Clear ALL state fields except messages to prevent contamination between queries
        cleaned_state = {
            # PRESERVE: Only conversation messages
            "messages": messages,
            
            # CLEAR: All processing state fields (as defined in EnhancedText2SQLState)
            "current_agent": None,
            "table_info": {},
            "context_data": None,
            "intent_data": None,
            "sql_parameters": None,
            "generated_sql": None,
            "execution_result": None,
            "extraction_result": None,
            "analysis_result": None,
            "sql_generation_response": None,
            "raw_llm_response": None,
            "errors": None,
            "agent_results": None,
            
            # CLEAR: Additional processing fields that may accumulate
            "enhanced_query": None,
            "query_enhancements": None,
            "entity_distinct_matches": None,
            "entity_matching_results": None,
            "distinct_value_matches": None,
            "semantic_analysis": None,
            "confidence_scores": None,
            "processing_metadata": None
        }
        
        self.logger.info("State completely cleaned - only messages preserved for new query processing")
        return cleaned_state

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
            graph_builder.add_node("query_enhancement_agent", self.query_enhancement_agent.execute)
            graph_builder.add_node("sql_generation_agent", self.sql_generation_agent.execute)
            graph_builder.add_node("sql_execution_agent", self.sql_execution_agent.execute)
            
            # Add state cleanup node
            graph_builder.add_node("cleanup_state", self._cleanup_state)
            
            # Define multi-agent workflow
            graph_builder.set_entry_point("cleanup_state")
            graph_builder.add_edge("cleanup_state", "table_data_agent")
            graph_builder.add_edge("table_data_agent", "context_analysis_agent")
            graph_builder.add_edge("context_analysis_agent", "intent_analysis_agent")
            graph_builder.add_edge("intent_analysis_agent", "query_enhancement_agent")
            graph_builder.add_edge("query_enhancement_agent", "sql_generation_agent")
            graph_builder.add_edge("sql_generation_agent", "sql_execution_agent")
            graph_builder.set_finish_point("sql_execution_agent")
            
            # Compile multi-agent graph
            compiled_graph = graph_builder.compile(
                checkpointer=self.memory,
                name="enhanced_query_extraction_multi_agent_graph" 
            )
            
            # If assistant_configuration is provided, create a wrapper that injects it into config
            if self.assistant_configuration:
                return self._create_config_wrapper(compiled_graph)
            
            self.logger.info("Enhanced Query Extraction Multi-Agent graph compiled successfully")
            return compiled_graph
            
        except Exception as e:
            self.logger.error(f"Failed to build Enhanced Query Extraction Multi-Agent graph: {e}")
            raise
    
    def _create_config_wrapper(self, compiled_graph):
        """Create a wrapper that automatically injects assistant configuration into the config"""
        class ConfigWrapper:
            def __init__(self, graph, assistant_config):
                self.graph = graph
                self.assistant_config = assistant_config
                # Delegate all attributes to the wrapped graph
                for attr in dir(graph):
                    if not attr.startswith('_') and attr not in ['invoke', 'ainvoke']:
                        setattr(self, attr, getattr(graph, attr))
            
            def invoke(self, state, config=None):
                # Prepare config with assistant_config injection
                if config is None:
                    config = {}
                config = config.copy()
                
                if "configurable" not in config:
                    config["configurable"] = {}
                
                # Ensure thread_id exists (required by langgraph checkpointer)
                if "thread_id" not in config["configurable"]:
                    config["configurable"]["thread_id"] = "1"
                
                # Convert assistant_config to dict if needed
                assistant_config_dict = (
                    self.assistant_config.to_dict() 
                    if hasattr(self.assistant_config, 'to_dict') 
                    else self.assistant_config
                )
                config["configurable"]["assistant_config"] = assistant_config_dict
                
                # Debug logging
                print(f"DEBUG: Assistant config being passed: {assistant_config_dict}")
                if assistant_config_dict:
                    print(f"DEBUG: Config keys: {list(assistant_config_dict.keys())}")
                
                return self.graph.invoke(state, config=config)
            
            def ainvoke(self, state, config=None):
                # Prepare config with assistant_config injection (async version)
                if config is None:
                    config = {}
                config = config.copy()
                
                if "configurable" not in config:
                    config["configurable"] = {}
                
                # Ensure thread_id exists (required by langgraph checkpointer)
                if "thread_id" not in config["configurable"]:
                    config["configurable"]["thread_id"] = "1"
                
                # Convert assistant_config to dict if needed
                assistant_config_dict = (
                    self.assistant_config.to_dict() 
                    if hasattr(self.assistant_config, 'to_dict') 
                    else self.assistant_config
                )
                config["configurable"]["assistant_config"] = assistant_config_dict
                
                # Debug logging
                print(f"DEBUG: Assistant config being passed: {assistant_config_dict}")
                if assistant_config_dict:
                    print(f"DEBUG: Config keys: {list(assistant_config_dict.keys())}")
                
                return self.graph.ainvoke(state, config=config)
        
        self.logger.info("Enhanced Query Extraction Multi-Agent graph compiled successfully with config wrapper")
        return ConfigWrapper(compiled_graph, self.assistant_configuration)

    def get_results_summary(self, final_state: Dict[str, Any]) -> Dict[str, Any]:
        """Generate comprehensive results summary from final state"""
        try:
            summary = {
                "success": True,
                "generated_sql": final_state.get("generated_sql", ""),
                "conversation_analysis": {},
                "agent_performance": {},
                "extraction_metrics": {},
                "errors": final_state.get("errors", {})
            }
            
            # Conversation analysis
            intent_data = final_state.get("intent_data", {})
            summary["conversation_analysis"] = {
                "conversation_type": intent_data.get("conversation_type", "unknown"),
                "confidence": intent_data.get("confidence", 0.0),
                "intent_category": intent_data.get("intent_category", "unknown"),
                "key_entities": len(intent_data.get("key_entities", [])),
                "reasoning": intent_data.get("reasoning", "")
            }
            
            # Agent performance metrics
            agent_results = final_state.get("agent_results", {})
            summary["agent_performance"] = {
                "total_agents": len(agent_results),
                "successful_agents": len([r for r in agent_results.values() if r.get("status") == "success"]),
                "failed_agents": len([r for r in agent_results.values() if r.get("status") == "error"]),
                "execution_details": agent_results
            }
            
            # Enhancement metrics
            query_enhancements = final_state.get("query_enhancements", {})
            table_info = final_state.get("table_info", {})
            
            summary["extraction_metrics"] = {
                "entity_matches": len(query_enhancements.get("entity_matches", [])),
                "replacements_made": query_enhancements.get("replacement_count", 0),
                "enhanced_query": final_state.get("enhanced_query", ""),
                "columns_analyzed": len(table_info.get("columns", [])),
                "searchable_columns": len([c for c in table_info.get("columns", []) if c.get("distinct_values")])
            }
            
            # Determine overall success
            if summary["errors"] or summary["agent_performance"]["failed_agents"] > 0:
                summary["success"] = False
                
            return summary
            
        except Exception as e:
            self.logger.error(f"Failed to generate results summary: {e}")
            return {
                "success": False,
                "error": str(e),
                "generated_sql": final_state.get("generated_sql", ""),
                "conversation_analysis": {},
                "agent_performance": {},
                "extraction_metrics": {}
            }

    def format_final_response(self, final_state: Dict[str, Any]) -> str:
        """Format final response with comprehensive information"""
        try:
            summary = self.get_results_summary(final_state)
            
            if not summary["success"]:
                error_msg = summary.get("error", "Unknown error occurred")
                return f"[ERROR] **Hata:** {error_msg}"
            
            sql_query = summary.get("generated_sql", "")
            if not sql_query:
                return "[ERROR] **SQL sorgusu oluşturulamadı**"
            
            # Build response
            response_parts = []
            
            # SQL Query
            response_parts.append(f"🔍 **Oluşturulan SQL Sorgusu:**\n```sql\n{sql_query}\n```")
            
            # Conversation Analysis
            conv_analysis = summary["conversation_analysis"]
            response_parts.append(f"""[CHART] **Analiz Sonuçları:**
• **Konuşma Türü:** {conv_analysis['conversation_type']}
• **Güven Skoru:** {conv_analysis['confidence']:.2f}
• **Intent Kategorisi:** {conv_analysis['intent_category']}
• **Tespit Edilen Varlıklar:** {conv_analysis['key_entities']} adet""")
            
            # Enhancement Metrics
            metrics = summary["extraction_metrics"]
            response_parts.append(f"""🎯 **Sorgu Geliştirme Metrikleri:**
• **Entity Eşleştirmeleri:** {metrics['entity_matches']} adet
• **Yapılan Değişimler:** {metrics['replacements_made']} adet
• **Geliştirilmiş Sorgu:** {metrics['enhanced_query'][:50]}{'...' if len(metrics['enhanced_query']) > 50 else ''}
• **Analiz Edilen Kolonlar:** {metrics['columns_analyzed']} adet
• **Aranabilir Kolonlar:** {metrics['searchable_columns']} adet""")
            
            # Agent Performance
            perf = summary["agent_performance"]
            response_parts.append(f"""[ROBOT] **Agent Performansı:**
• **Toplam Agent:** {perf['total_agents']}
• **Başarılı:** {perf['successful_agents']}
• **Başarısız:** {perf['failed_agents']}""")
            
            return "\n\n".join(response_parts)
            
        except Exception as e:
            self.logger.error(f"Failed to format final response: {e}")
            return f"[ERROR] **Response formatting failed:** {str(e)}"

    def execute_workflow(self, user_query: str, conversation_id: str = None, **kwargs) -> Dict[str, Any]:
        """Execute the complete Enhanced Query Extraction workflow"""
        execution_start_time = time.time()
        
        try:
            self.logger.info(f"Starting Enhanced Query Extraction workflow for query: {user_query[:100]}...")
            
            # Build graph if not already built
            if not hasattr(self, 'graph') or self.graph is None:
                self.graph = self.build_graph()
            
            # Execute workflow
            result = self.run_workflow(
                user_query=user_query,
                conversation_id=conversation_id,
                **kwargs
            )
            
            execution_time = time.time() - execution_start_time
            
            # Format final response
            final_response = self.format_final_response(result.get("final_state", {}))
            
            # Add execution metadata
            result["execution_metadata"] = {
                "total_execution_time": execution_time,
                "workflow_type": "enhanced_query_extraction",
                "agents_executed": len(result.get("final_state", {}).get("agent_results", {})),
                "success": result.get("success", False)
            }
            
            result["formatted_response"] = final_response
            
            self.logger.info(f"Enhanced Query Extraction workflow completed in {execution_time:.2f}s")
            return result
            
        except Exception as e:
            self.logger.error(f"Enhanced Query Extraction workflow failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "final_state": {},
                "formatted_response": f"[ERROR] **Workflow failed:** {str(e)}",
                "execution_metadata": {
                    "total_execution_time": time.time() - execution_start_time,
                    "workflow_type": "enhanced_query_extraction",
                    "agents_executed": 0,
                    "success": False
                }
            }