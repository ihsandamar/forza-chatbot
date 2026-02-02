"""
Context Management Middleware

Custom LangChain middleware for managing active query context across
agent execution. Tracks SQL query state, history, and provides context
injection for modification queries.

Features:
- Active query context persistence
- Query history with checkpoints (last 10)
- Context injection into tool calls
- Session-based state management
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime
from langchain_core.agents import AgentMiddleware
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# STATE SCHEMA
# =============================================================================

class ActiveQueryContext(BaseModel):
    """Active SQL query context."""
    current_table: str = ""
    current_sql: str = ""
    applied_filters: List[Dict[str, Any]] = Field(default_factory=list)
    grouping_columns: List[str] = Field(default_factory=list)
    order_by_columns: List[str] = Field(default_factory=list)
    result_sample: Optional[List[Dict]] = None
    result_row_count: int = 0
    last_execution_time: str = Field(default_factory=lambda: datetime.now().isoformat())
    confidence_score: float = 0.0


class QueryCheckpoint(BaseModel):
    """Query checkpoint for undo/redo."""
    version: int
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    active_context: ActiveQueryContext
    user_message: str


class ContextManagementState(BaseModel):
    """Custom middleware state for context management."""
    active_query_context: Optional[ActiveQueryContext] = None
    query_history: List[QueryCheckpoint] = Field(default_factory=list, max_length=10)
    session_id: Optional[str] = None


# =============================================================================
# CONTEXT MANAGEMENT MIDDLEWARE
# =============================================================================

class ContextManagementMiddleware(AgentMiddleware):
    """
    Manages active query context across agent execution.

    Hooks:
    - before_agent: Load context from session
    - after_agent: Persist context to session
    - wrap_tool_call: Inject context into text2sql_tool calls
    """

    def __init__(self, session_store: Optional[Dict] = None):
        """
        Initialize context management middleware.

        Args:
            session_store: Optional external session storage
                          (e.g., Redis, database) for context persistence
        """
        super().__init__()
        self.session_store = session_store or {}
        self.state_schema = ContextManagementState
        logger.info("[CONTEXT_MIDDLEWARE] Initialized")

    def before_agent(
        self,
        inputs: Dict[str, Any],
        config: Dict[str, Any],
        state: ContextManagementState
    ) -> Dict[str, Any]:
        """
        Load context from session before agent execution.

        Args:
            inputs: Agent inputs
            config: Runtime config
            state: Middleware state

        Returns:
            Updated inputs
        """
        session_id = config.get("configurable", {}).get("thread_id")

        if session_id:
            logger.info(f"[CONTEXT_MIDDLEWARE] Loading context for session: {session_id}")

            # Load from session store
            session_data = self.session_store.get(session_id, {})
            stored_context = session_data.get("active_query_context")
            stored_history = session_data.get("query_history", [])

            if stored_context:
                state.active_query_context = ActiveQueryContext(**stored_context)
                logger.info(f"[CONTEXT_MIDDLEWARE] Context loaded: table={state.active_query_context.current_table}, rows={state.active_query_context.result_row_count}")

            if stored_history:
                state.query_history = [QueryCheckpoint(**cp) for cp in stored_history]
                logger.info(f"[CONTEXT_MIDDLEWARE] History loaded: {len(state.query_history)} checkpoints")

            state.session_id = session_id

        return inputs

    def after_agent(
        self,
        outputs: Dict[str, Any],
        config: Dict[str, Any],
        state: ContextManagementState
    ) -> Dict[str, Any]:
        """
        Persist context to session after agent execution.

        Args:
            outputs: Agent outputs
            config: Runtime config
            state: Middleware state

        Returns:
            Updated outputs
        """
        if state.session_id:
            logger.info(f"[CONTEXT_MIDDLEWARE] Persisting context for session: {state.session_id}")

            # Prepare session data
            session_data = self.session_store.get(state.session_id, {})

            if state.active_query_context:
                session_data["active_query_context"] = state.active_query_context.dict()
                logger.info(f"[CONTEXT_MIDDLEWARE] Context saved: {state.active_query_context.current_table}")

            if state.query_history:
                session_data["query_history"] = [cp.dict() for cp in state.query_history]
                logger.info(f"[CONTEXT_MIDDLEWARE] History saved: {len(state.query_history)} checkpoints")

            # Persist
            self.session_store[state.session_id] = session_data

        return outputs

    async def wrap_tool_call(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        invoke_tool: callable,
        config: Dict[str, Any],
        state: ContextManagementState
    ) -> Any:
        """
        Inject context into tool calls.

        For text2sql_tool: Add active_query_context
        For visualization_tool: Pass through
        For rollback_tool: Execute rollback logic

        Args:
            tool_name: Name of the tool being called
            tool_input: Tool input arguments
            invoke_tool: Function to invoke the tool
            config: Runtime config
            state: Middleware state

        Returns:
            Tool output
        """
        logger.info(f"[CONTEXT_MIDDLEWARE] Intercepting tool call: {tool_name}")

        # =====================================================================
        # TEXT2SQL TOOL - Context Injection
        # =====================================================================
        if tool_name == "text2sql_tool":
            # Inject active context if available
            if state.active_query_context and not tool_input.get("context"):
                logger.info("[CONTEXT_MIDDLEWARE] Injecting active context into text2sql_tool")
                tool_input["context"] = state.active_query_context.dict()

            # Invoke tool
            result = await invoke_tool(tool_input)

            # Update context if query succeeded
            if result and not result.get("error") and result.get("results"):
                logger.info("[CONTEXT_MIDDLEWARE] Updating active context from text2sql result")
                self._update_context_from_text2sql(result, state, tool_input.get("user_query", ""))

            return result

        # =====================================================================
        # ROLLBACK TOOL - Execute Rollback
        # =====================================================================
        elif tool_name == "rollback_tool":
            target_version = tool_input.get("version")

            if not state.query_history or len(state.query_history) < 2:
                logger.warning("[CONTEXT_MIDDLEWARE] Not enough history for rollback")
                return {
                    "success": False,
                    "message": "Geri alınacak önceki sorgu yok.",
                    "restored_context": None
                }

            # Get target checkpoint
            if target_version:
                checkpoint = next((cp for cp in state.query_history if cp.version == target_version), None)
            else:
                # Default: previous (second to last)
                checkpoint = state.query_history[-2]

            if checkpoint:
                logger.info(f"[CONTEXT_MIDDLEWARE] Rolling back to version {checkpoint.version}")
                state.active_query_context = checkpoint.active_context

                return {
                    "success": True,
                    "message": f"Önceki sorguya geri dönüldü (v{checkpoint.version})",
                    "restored_context": checkpoint.active_context.dict()
                }
            else:
                return {
                    "success": False,
                    "message": "Belirtilen versiyon bulunamadı.",
                    "restored_context": None
                }

        # =====================================================================
        # GET CONTEXT TOOL - Return Context
        # =====================================================================
        elif tool_name == "get_context_tool":
            if state.active_query_context:
                return {
                    "has_context": True,
                    "context_summary": self._format_context_summary(state.active_query_context),
                    "context": state.active_query_context.dict()
                }
            else:
                return {
                    "has_context": False,
                    "context_summary": "Henüz aktif bir sorgu yok.",
                    "context": None
                }

        # =====================================================================
        # OTHER TOOLS - Pass through
        # =====================================================================
        else:
            return await invoke_tool(tool_input)

    def _update_context_from_text2sql(
        self,
        text2sql_output: Dict[str, Any],
        state: ContextManagementState,
        user_message: str
    ):
        """Update active context from text2sql output."""
        sql_queries = text2sql_output.get("sql_queries", [])
        results = text2sql_output.get("results", [])
        parsed_intent = text2sql_output.get("parsed_intent", {})
        resolved_steps = text2sql_output.get("resolved_steps", [])

        # Extract filters, grouping, ordering
        applied_filters = []
        grouping_columns = []
        order_by_columns = []

        steps = resolved_steps if resolved_steps else parsed_intent.get("steps", [])
        for step in steps:
            # Filters
            for f in step.get("filters", []):
                applied_filters.append({
                    "column": f.get("field_hint", ""),
                    "operator": f.get("operator", "="),
                    "value": f.get("resolved_value") or f.get("value_hint", "")
                })

            # Group by
            grouping_columns.extend(step.get("group_by", []))

            # Order by
            order_by = step.get("order_by")
            if order_by:
                col = order_by.get("field_hint", "")
                direction = order_by.get("direction", "ASC")
                if col:
                    order_by_columns.append(f"{col} {direction}")

        # Create new context
        new_context = ActiveQueryContext(
            current_table="MasterReportDocumentTable",  # Default
            current_sql=sql_queries[0] if sql_queries else "",
            applied_filters=applied_filters,
            grouping_columns=list(set(grouping_columns)),
            order_by_columns=order_by_columns,
            result_sample=results[:5] if results else None,
            result_row_count=len(results) if results else 0,
            last_execution_time=datetime.now().isoformat(),
            confidence_score=0.8
        )

        # Create checkpoint
        checkpoint = QueryCheckpoint(
            version=len(state.query_history) + 1,
            active_context=new_context,
            user_message=user_message
        )

        # Update state
        state.active_query_context = new_context
        state.query_history.append(checkpoint)

        # Keep only last 10
        if len(state.query_history) > 10:
            state.query_history = state.query_history[-10:]

        logger.info(f"[CONTEXT_MIDDLEWARE] Context updated: {new_context.result_row_count} rows, v{checkpoint.version}")

    def _format_context_summary(self, context: ActiveQueryContext) -> str:
        """Format context for display."""
        filters_text = ", ".join([f"{f['column']}={f['value']}" for f in context.applied_filters])
        return f"""Aktif Sorgu:
Tablo: {context.current_table}
Filtreler: {filters_text or 'Yok'}
Gruplama: {', '.join(context.grouping_columns) or 'Yok'}
Sonuç: {context.result_row_count} satır"""
