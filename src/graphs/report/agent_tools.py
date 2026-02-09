"""
LangChain Tools for Report Agent

Converts existing LangGraph subgraphs to LangChain tools for use in
the new agent-based architecture with custom middleware.

Tools:
- text2sql_tool: Generate and execute SQL queries
- visualization_tool: Create data visualizations
- rollback_tool: Rollback to previous query checkpoint
- get_context_tool: Get current active query context
"""

import logging
from typing import Any, Dict, Optional
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


# =============================================================================
# TEXT2SQL TOOL
# =============================================================================

@tool
async def text2sql_tool(
    user_query: str,
    context: Optional[Dict[str, Any]] = None,
    selected_column: Optional[str] = None,
    selected_value: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate and execute SQL query from natural language.

    This tool wraps the GenericText2SQL graph and handles:
    - Query parsing and intent detection
    - SQL generation with schema metadata
    - Query execution
    - Result formatting

    Args:
        user_query: Natural language query from user
        context: Optional active query context for modification queries
        selected_column: User-selected column (from HITL clarification)
        selected_value: User-selected value (from HITL clarification)

    Returns:
        Dict containing:
        - sql_queries: List[str] - Generated SQL queries
        - results: List[dict] - Query results
        - resolution_metadata: Optional[dict] - Ambiguity metadata
        - error: Optional[str] - Error message if failed
    """
    from src.graphs.generic_text2sql.graph import GenericText2SQLGraph
    from src.models.llm import LLM
    from src.config.config import get_config

    logger.info(f"[TEXT2SQL_TOOL] Processing query: {user_query[:100]}...")

    try:
        # Initialize text2sql graph
        config = get_config()
        llm = LLM(
            provider=config.llm.provider,
            model=config.llm.model,
            temperature=config.llm.temperature,
            api_key=config.llm.api_key
        )

        text2sql_graph = GenericText2SQLGraph(llm=llm).build_graph()

        # Build enhanced query with clarifications
        enhanced_query = user_query

        if selected_column:
            logger.info(f"[TEXT2SQL_TOOL] Using selected column: {selected_column}")
            enhanced_query = f"""{user_query}

ÖNEMLİ NOT: Kullanıcı belirsiz alan için '{selected_column}' kolonunu seçti. Bu kolonu kullan."""

        if selected_value:
            logger.info(f"[TEXT2SQL_TOOL] Using selected value: {selected_value}")
            enhanced_query = f"""{user_query}

ÖNEMLİ NOT: Kullanıcı filtre değeri olarak '{selected_value}' seçti. Bu değeri kullan."""

        # Add context hint for modification queries
        if context:
            logger.info(f"[TEXT2SQL_TOOL] Active context detected, adding modification hint")
            context_sql = context.get("current_sql", "")
            context_filters = context.get("applied_filters", [])

            if context_sql:
                enhanced_query = f"""MEVCUT SORGU BAĞLAMI:
Mevcut SQL: {context_sql[:500]}
Mevcut Filtreler: {context_filters}

KULLANICI TALEBİ: {user_query}

GÖREV: Mevcut sorguyu modifiye et veya genişlet."""

        # Prepare input
        text2sql_input = {
            "user_query": enhanced_query,
            "parsed_intent": None,
            "enriched_metadata": None,
            "resolved_steps": None,
            "resolution_metadata": None,
            "sql_queries": None,
            "results": None,
            "final_response": None,
            "error": None
        }

        # Invoke text2sql graph
        result = await text2sql_graph.ainvoke(text2sql_input)

        logger.info(f"[TEXT2SQL_TOOL] Query completed: {len(result.get('results', []))} rows")

        return {
            "sql_queries": result.get("sql_queries", []),
            "results": result.get("results", []),
            "resolution_metadata": result.get("resolution_metadata"),
            "parsed_intent": result.get("parsed_intent"),
            "error": result.get("error")
        }

    except Exception as e:
        logger.error(f"[TEXT2SQL_TOOL] Error: {e}", exc_info=True)
        return {
            "sql_queries": [],
            "results": [],
            "resolution_metadata": None,
            "error": f"Text2SQL error: {str(e)}"
        }


# =============================================================================
# VISUALIZATION TOOL
# =============================================================================

@tool
async def visualization_tool(
    sql_results: Dict[str, Any],
    chart_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create data visualization from SQL results.

    Args:
        sql_results: Output from text2sql_tool
        chart_type: Optional specific chart type (bar, line, pie, etc.)

    Returns:
        Dict containing:
        - visualization_output: Plotly HTML
        - summary: Text description
        - needs_graph: bool
    """
    from src.graphs.visualization.graph import build_visualization_graph
    from src.models.llm import LLM
    from src.config.config import get_config

    logger.info("[VISUALIZATION_TOOL] Creating visualization...")

    try:
        # Initialize visualization graph
        config = get_config()
        llm = LLM(
            provider=config.llm.provider,
            model=config.llm.model,
            temperature=config.llm.temperature,
            api_key=config.llm.api_key
        )

        viz_graph = build_visualization_graph(llm=llm)

        # Invoke visualization graph
        result = await viz_graph.ainvoke(sql_results)

        logger.info("[VISUALIZATION_TOOL] Visualization created")

        return {
            "visualization_output": result.get("visualization_output"),
            "plotly_html_snippet": result.get("plotly_html_snippet"),
            "error": result.get("error")
        }

    except Exception as e:
        logger.error(f"[VISUALIZATION_TOOL] Error: {e}", exc_info=True)
        return {
            "visualization_output": None,
            "error": f"Visualization error: {str(e)}"
        }


# =============================================================================
# ROLLBACK TOOL
# =============================================================================

@tool
def rollback_tool(version: Optional[int] = None) -> Dict[str, Any]:
    """
    Rollback to previous query checkpoint.

    Args:
        version: Optional specific version to rollback to (default: previous)

    Returns:
        Dict containing:
        - success: bool
        - restored_context: ActiveQueryContext
        - message: str
    """
    logger.info(f"[ROLLBACK_TOOL] Rollback requested (version: {version})")

    # Note: Actual rollback logic will be handled by ContextManagementMiddleware
    # This tool just signals the intent
    return {
        "success": True,
        "action": "rollback",
        "target_version": version or "previous",
        "message": "Rollback signal sent to middleware"
    }


# =============================================================================
# CONTEXT INFO TOOL
# =============================================================================

@tool
def get_context_tool() -> Dict[str, Any]:
    """
    Get current active query context information.

    Returns:
        Dict containing:
        - has_context: bool
        - context_summary: str
        - message: str
    """
    logger.info("[GET_CONTEXT_TOOL] Context info requested")

    # Note: Actual context will be provided by ContextManagementMiddleware
    # This tool just signals the request
    return {
        "action": "get_context",
        "message": "Context request sent to middleware"
    }


# =============================================================================
# TOOL LIST
# =============================================================================

REPORT_AGENT_TOOLS = [
    text2sql_tool,
    visualization_tool,
    rollback_tool,
    get_context_tool
]
