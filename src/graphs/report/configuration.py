"""
Report Agent Configuration

Unified configuration schema for Report Agent with embedded Text2SQL support.
Extends GenericSQLAssistantConfiguration to support runtime config switching.

Runtime Config Example:
    config = {
        "configurable": {
            # Text2SQL config (runtime switchable)
            "table_name": "MasterReportDocumentTable",
            "query": "SELECT * FROM MasterReportDocumentTable",
            "column_metadata": {...},
            "business_rules": [...],

            # Report Agent config
            "enable_hitl": True,
            "enable_business_insights": True,
            "enable_llm_interpretation": True,

            # Optimization flags
            "enable_fast_path": True,
            "enable_parallel_execution": True,
            "enable_merged_text2sql": True
        }
    }

    # Use with graph
    result = await graph.ainvoke(input_state, config=config)
"""

from typing import Optional, List, Dict, Any
from pydantic import Field

from src.graphs.generic_text2sql.assistant_configuration import GenericSQLAssistantConfiguration


class ReportAgentConfiguration(GenericSQLAssistantConfiguration):
    """
    Unified configuration for Report Agent with embedded Text2SQL.

    Extends GenericSQLAssistantConfiguration to include Report Agent specific
    settings while preserving runtime configurability of Text2SQL components.

    Runtime Switchable Fields:
    -------------------------
    All GenericSQLAssistantConfiguration fields can be changed at runtime:
    - table_name: Target table for queries
    - query: Table creation query
    - column_metadata: Table-specific metadata
    - business_rules: Context-specific business rules

    Report Agent Fields:
    -------------------
    - enable_hitl: Enable Human-in-the-Loop features
    - enable_llm_conversation: Enable LLM-powered conversation management
    - enable_business_insights: Enable business insights extraction
    - enable_llm_interpretation: Enable LLM visualization decisions
    - enable_natural_response: Enable natural language responses

    Optimization Fields:
    -------------------
    - enable_semantic_cache: Enable semantic caching for LLM calls
    - enable_fast_path: Enable fast-path intent classification
    - enable_parallel_execution: Enable parallel insights+viz execution
    - enable_merged_text2sql: Enable Text2SQL node merge (vs separate graph)
    """

    # =========================================================================
    # TEXT2SQL CONFIG (inherited from GenericSQLAssistantConfiguration)
    # =========================================================================
    # report_name: str
    # description: str
    # table_name: str - RUNTIME SWITCHABLE
    # query: str - RUNTIME SWITCHABLE
    # column_metadata: Dict[str, str] - RUNTIME SWITCHABLE
    # business_rules: List[Dict[str, Any]] - RUNTIME SWITCHABLE

    # =========================================================================
    # REPORT AGENT CONFIG
    # =========================================================================

    enable_hitl: bool = Field(
        default=True,
        description="Enable Human-in-the-Loop features (interrupt_before, clarifications)"
    )

    enable_llm_conversation: bool = Field(
        default=True,
        description="Enable LLM-powered conversation management (ConversationManager)"
    )

    enable_business_insights: bool = Field(
        default=True,
        description="Enable business insights extraction (BusinessContextTracker)"
    )

    enable_llm_interpretation: bool = Field(
        default=True,
        description="Enable LLM-powered visualization decisions (ReportInterpreter)"
    )

    enable_natural_response: bool = Field(
        default=True,
        description="Enable natural language response generation (ResponseGenerator)"
    )

    # =========================================================================
    # OPTIMIZATION FLAGS (Phase 1 + Hybrid Merge)
    # =========================================================================

    enable_semantic_cache: bool = Field(
        default=True,
        description="Enable semantic caching for LLM calls (Phase 1 optimization)"
    )

    enable_fast_path: bool = Field(
        default=True,
        description="Enable fast-path intent classification (Phase 1 optimization)"
    )

    enable_parallel_execution: bool = Field(
        default=True,
        description="Enable parallel insights+viz execution (Phase 1 optimization)"
    )

    enable_merged_text2sql: bool = Field(
        default=True,
        description="Enable Text2SQL node merge into Report Agent (Hybrid merge optimization)"
    )

    # =========================================================================
    # TEXT2SQL SPECIFIC FLAGS (Runtime switchable)
    # =========================================================================

    enable_value_resolution: bool = Field(
        default=True,
        description="Enable fuzzy value resolution in Text2SQL"
    )

    enable_business_rules_retrieval: bool = Field(
        default=True,
        description="Enable business rules retrieval from vector store"
    )

    # =========================================================================
    # ADVANCED CONFIG
    # =========================================================================

    semantic_cache_threshold: float = Field(
        default=0.95,
        description="Semantic similarity threshold for cache hits (0.0-1.0)"
    )

    semantic_cache_ttl: int = Field(
        default=3600,
        description="Semantic cache TTL in seconds (default: 1 hour)"
    )

    semantic_cache_max_size: int = Field(
        default=2000,
        description="Maximum semantic cache size (LRU eviction)"
    )

    fast_path_confidence_threshold: float = Field(
        default=0.85,
        description="Confidence threshold for fast-path classification"
    )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def to_text2sql_config(self) -> Dict[str, Any]:
        """
        Extract Text2SQL specific config.

        Returns:
            Dict with Text2SQL configuration
        """
        return {
            "table_name": self.table_name,
            "query": self.query,
            "column_metadata": self.column_metadata,
            "business_rules": self.business_rules,
            "enable_value_resolution": self.enable_value_resolution,
            "enable_business_rules_retrieval": self.enable_business_rules_retrieval
        }

    def to_report_config(self) -> Dict[str, Any]:
        """
        Extract Report Agent specific config.

        Returns:
            Dict with Report Agent configuration
        """
        return {
            "enable_hitl": self.enable_hitl,
            "enable_llm_conversation": self.enable_llm_conversation,
            "enable_business_insights": self.enable_business_insights,
            "enable_llm_interpretation": self.enable_llm_interpretation,
            "enable_natural_response": self.enable_natural_response
        }

    def to_optimization_config(self) -> Dict[str, Any]:
        """
        Extract optimization flags.

        Returns:
            Dict with optimization configuration
        """
        return {
            "enable_semantic_cache": self.enable_semantic_cache,
            "enable_fast_path": self.enable_fast_path,
            "enable_parallel_execution": self.enable_parallel_execution,
            "enable_merged_text2sql": self.enable_merged_text2sql,
            "semantic_cache_threshold": self.semantic_cache_threshold,
            "semantic_cache_ttl": self.semantic_cache_ttl,
            "semantic_cache_max_size": self.semantic_cache_max_size,
            "fast_path_confidence_threshold": self.fast_path_confidence_threshold
        }
