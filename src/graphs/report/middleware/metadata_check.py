"""
Metadata Check Middleware with HITL

Custom LangChain middleware for detecting metadata ambiguities in
text2sql output and triggering Human-in-the-Loop (HITL) clarification.

Features:
- Column ambiguity detection
- Value ambiguity detection (fuzzy matching)
- HITL question generation
- Agent jump for flow interruption
- Clarification resumption
"""

import logging
from typing import Any, Dict, List, Optional
from langchain_core.agents import AgentMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# STATE SCHEMA
# =============================================================================

class PendingQuestion(BaseModel):
    """Pending HITL question."""
    question: str
    options: List[str]
    context: str = ""
    question_type: str = "column"  # "column", "value", "table"


class MetadataCheckState(BaseModel):
    """Custom middleware state for metadata checking."""
    pending_question: Optional[PendingQuestion] = None
    waiting_for_clarification: bool = False
    selected_column: Optional[str] = None
    selected_value: Optional[str] = None
    clarification_type: Optional[str] = None


# =============================================================================
# METADATA CHECK MIDDLEWARE
# =============================================================================

class MetadataCheckMiddleware(AgentMiddleware):
    """
    Detects metadata ambiguities and triggers HITL clarification.

    Hooks:
    - after_model: Check text2sql tool output for ambiguities
    - Agent jump: Interrupt flow if clarification needed
    """

    def __init__(self):
        """Initialize metadata check middleware."""
        super().__init__()
        self.state_schema = MetadataCheckState
        logger.info("[METADATA_MIDDLEWARE] Initialized")

    async def wrap_tool_call(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        invoke_tool: callable,
        config: Dict[str, Any],
        state: MetadataCheckState
    ) -> Any:
        """
        Intercept text2sql_tool output and check for ambiguities.

        If ambiguity detected:
        1. Create pending question
        2. Set waiting flag
        3. Return special signal to agent

        Args:
            tool_name: Name of the tool
            tool_input: Tool inputs
            invoke_tool: Tool invocation function
            config: Runtime config
            state: Middleware state

        Returns:
            Tool output or HITL signal
        """
        # Only intercept text2sql_tool
        if tool_name != "text2sql_tool":
            return await invoke_tool(tool_input)

        logger.info("[METADATA_MIDDLEWARE] Intercepting text2sql_tool call")

        # Check if we're retrying with clarification
        if state.selected_column or state.selected_value:
            logger.info(f"[METADATA_MIDDLEWARE] Retry with clarification: col={state.selected_column}, val={state.selected_value}")

            # Inject clarification into tool input
            if state.selected_column:
                tool_input["selected_column"] = state.selected_column
            if state.selected_value:
                tool_input["selected_value"] = state.selected_value

            # Clear clarification state
            state.selected_column = None
            state.selected_value = None
            state.clarification_type = None

        # Invoke text2sql tool
        result = await invoke_tool(tool_input)

        # Check for errors
        if result.get("error"):
            logger.warning(f"[METADATA_MIDDLEWARE] Text2SQL error: {result['error']}")
            return result

        # =====================================================================
        # METADATA AMBIGUITY CHECK
        # =====================================================================
        resolution_metadata = result.get("resolution_metadata")

        if not resolution_metadata:
            logger.info("[METADATA_MIDDLEWARE] No metadata to check")
            return result

        logger.info("[METADATA_MIDDLEWARE] Checking resolution_metadata for ambiguities...")

        # ---------------------------------------------------------------------
        # Column Ambiguity Check
        # ---------------------------------------------------------------------
        ambiguous_fields = resolution_metadata.get("ambiguous_fields", [])

        if ambiguous_fields and len(ambiguous_fields) > 0:
            ambiguous_field = ambiguous_fields[0]
            field_hint = ambiguous_field.get("field_hint", "Bilinmeyen alan")
            candidates = ambiguous_field.get("candidates", [])

            if candidates and len(candidates) > 1:
                logger.info(f"[METADATA_MIDDLEWARE] Column ambiguity detected: {field_hint} -> {len(candidates)} candidates")

                # Extract column names
                column_options = [c.get("column_name", str(c)) for c in candidates[:5]]

                # Create pending question
                pending_q = PendingQuestion(
                    question=f"'{field_hint}' için hangi kolonu kullanmak istiyorsunuz?",
                    options=column_options,
                    context=f"'{field_hint}' için birden fazla kolon bulundu.",
                    question_type="column"
                )

                state.pending_question = pending_q
                state.waiting_for_clarification = True

                logger.info(f"[METADATA_MIDDLEWARE] HITL question created: {pending_q.question}")

                # Return HITL signal
                return {
                    "hitl_required": True,
                    "pending_question": pending_q.dict(),
                    "original_result": result
                }

        # ---------------------------------------------------------------------
        # Value Ambiguity Check
        # ---------------------------------------------------------------------
        fuzzy_matches = resolution_metadata.get("fuzzy_matches", [])

        if fuzzy_matches and len(fuzzy_matches) > 0:
            fuzzy_match = fuzzy_matches[0]
            field_hint = fuzzy_match.get("field_hint", "Bilinmeyen alan")
            value_hint = fuzzy_match.get("value_hint", "")
            matched_values = fuzzy_match.get("matched_values", [])

            if matched_values and len(matched_values) > 1:
                logger.info(f"[METADATA_MIDDLEWARE] Value ambiguity detected: '{value_hint}' -> {len(matched_values)} matches")

                # Extract top 5 values
                value_options = [str(v) for v in matched_values[:5]]

                # Create pending question
                pending_q = PendingQuestion(
                    question=f"'{value_hint}' için hangi değeri kullanmak istiyorsunuz?",
                    options=value_options,
                    context=f"'{field_hint}' kolonunda '{value_hint}' için birden fazla eşleşme bulundu.",
                    question_type="value"
                )

                state.pending_question = pending_q
                state.waiting_for_clarification = True

                logger.info(f"[METADATA_MIDDLEWARE] HITL question created: {pending_q.question}")

                # Return HITL signal
                return {
                    "hitl_required": True,
                    "pending_question": pending_q.dict(),
                    "original_result": result
                }

        # No ambiguity detected
        logger.info("[METADATA_MIDDLEWARE] No ambiguity detected, proceeding normally")
        return result

    def process_user_clarification(
        self,
        user_response: str,
        state: MetadataCheckState
    ) -> Dict[str, Any]:
        """
        Process user clarification response.

        Args:
            user_response: User's selected option
            state: Middleware state

        Returns:
            Processing result
        """
        if not state.pending_question:
            logger.warning("[METADATA_MIDDLEWARE] No pending question to process")
            return {"error": "No pending question"}

        logger.info(f"[METADATA_MIDDLEWARE] Processing clarification: {user_response}")

        question_type = state.pending_question.question_type

        if question_type == "column":
            state.selected_column = user_response
            state.clarification_type = "column"
            logger.info(f"[METADATA_MIDDLEWARE] Column selected: {user_response}")

        elif question_type == "value":
            state.selected_value = user_response
            state.clarification_type = "value"
            logger.info(f"[METADATA_MIDDLEWARE] Value selected: {user_response}")

        # Clear pending question
        state.pending_question = None
        state.waiting_for_clarification = False

        return {
            "success": True,
            "clarification_type": state.clarification_type,
            "retry_required": True
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_hitl_question(pending_question: PendingQuestion) -> str:
    """
    Format HITL question for display to user.

    Args:
        pending_question: Pending question object

    Returns:
        Formatted question string
    """
    parts = [
        f"❓ {pending_question.question}",
        "",
        "Seçenekler:"
    ]

    for i, option in enumerate(pending_question.options, 1):
        parts.append(f"  {i}. {option}")

    if pending_question.context:
        parts.extend(["", f"ℹ️ {pending_question.context}"])

    return "\n".join(parts)
