"""
Intent Classification Middleware

Custom LangChain middleware for context-aware intent classification.
Determines if user wants to create new query or modify existing one.

Features:
- LLM-based intent classification
- Context-aware detection (references to previous query)
- Modification vs new query distinction
- Confidence scoring
"""

import logging
from typing import Any, Dict, Optional
from langchain_core.agents import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# INTENT TYPES
# =============================================================================

class IntentType(str, Enum):
    """User intent types."""
    NEW_QUERY = "new_query"
    MODIFY_FILTER = "modify_filter"
    MODIFY_AGGREGATION = "modify_aggregation"
    MODIFY_COLUMNS = "modify_columns"
    MODIFY_ORDER = "modify_order"
    VISUALIZE = "visualize"
    ROLLBACK = "rollback"
    CLARIFY = "clarify"
    UNKNOWN = "unknown"


# =============================================================================
# STATE SCHEMA
# =============================================================================

class IntentClassificationResult(BaseModel):
    """Intent classification result."""
    intent_type: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    requires_clarification: bool = False
    extracted_entities: Dict[str, Any] = Field(default_factory=dict)


class IntentClassificationState(BaseModel):
    """Custom middleware state for intent classification."""
    current_intent: Optional[IntentClassificationResult] = None
    classification_timestamp: Optional[str] = None


# =============================================================================
# INTENT CLASSIFICATION MIDDLEWARE
# =============================================================================

class IntentClassificationMiddleware(AgentMiddleware):
    """
    Context-aware intent classification for conversational queries.

    Hooks:
    - before_model: Classify user intent before agent decides on tools
    """

    # Context reference triggers
    CONTEXT_REFERENCE_TRIGGERS = [
        "burdaki", "buradaki", "bunun", "bunların", "şunun", "şunların",
        "bu kategorinin", "bu ürünlerin", "bu şubenin", "bu sonuçların",
        "peki", "peki bunun", "onun", "onların", "bunlar", "şunlar",
        "gösterdiğin", "verdiğin", "getirdiğin",
        "yukarıdaki", "önceki", "az önceki", "az önce"
    ]

    # Modification triggers
    MODIFICATION_TRIGGERS = [
        "sadece", "için", "filtrele", "hariç", "dahil",
        "ekle", "çıkar", "kaldır", "bunu da", "şunu da"
    ]

    def __init__(self, llm: BaseChatModel):
        """
        Initialize intent classification middleware.

        Args:
            llm: Language model for classification
        """
        super().__init__()
        self.llm = llm
        self.state_schema = IntentClassificationState
        logger.info("[INTENT_MIDDLEWARE] Initialized with LLM-based classification")

    def before_model(
        self,
        messages: list,
        config: Dict[str, Any],
        state: IntentClassificationState
    ) -> list:
        """
        Classify user intent before model execution.

        This runs BEFORE the agent decides which tools to use,
        allowing us to guide tool selection based on intent.

        Args:
            messages: Conversation messages
            config: Runtime config
            state: Middleware state

        Returns:
            Potentially modified messages with intent context
        """
        # Get last user message
        user_message = None
        for msg in reversed(messages):
            if msg.type == "human":
                user_message = msg.content
                break

        if not user_message:
            logger.warning("[INTENT_MIDDLEWARE] No user message found")
            return messages

        logger.info(f"[INTENT_MIDDLEWARE] Classifying intent for: {user_message[:50]}...")

        # Get context from ContextManagementMiddleware (if available)
        # Note: This requires accessing other middleware state
        # For now, we'll use simple pattern matching
        # TODO: Access ContextManagementMiddleware state properly

        # Simple classification based on triggers
        intent_result = self._classify_simple(user_message)

        # Store in state
        state.current_intent = intent_result

        logger.info(f"[INTENT_MIDDLEWARE] Intent: {intent_result.intent_type.value} (confidence: {intent_result.confidence})")

        # Add intent as system message for agent guidance
        from langchain_core.messages import SystemMessage

        intent_guidance = SystemMessage(content=f"""
INTENT CLASSIFICATION:
- Type: {intent_result.intent_type.value}
- Confidence: {intent_result.confidence}
- Entities: {intent_result.extracted_entities}

{self._get_tool_guidance(intent_result.intent_type)}
""")

        # Insert guidance before last user message
        messages_with_intent = messages[:-1] + [intent_guidance, messages[-1]]

        return messages_with_intent

    def _classify_simple(self, user_message: str) -> IntentClassificationResult:
        """
        Simple rule-based classification.

        TODO: Replace with LLM-based classification for better accuracy.

        Args:
            user_message: User's message

        Returns:
            Classification result
        """
        message_lower = user_message.lower()

        # Check for context references
        context_ref_score = sum(1 for trigger in self.CONTEXT_REFERENCE_TRIGGERS if trigger in message_lower)

        if context_ref_score > 0:
            logger.info(f"[INTENT_MIDDLEWARE] Context reference detected (score: {context_ref_score})")
            return IntentClassificationResult(
                intent_type=IntentType.MODIFY_FILTER,
                confidence=min(0.85 + context_ref_score * 0.05, 0.95),
                extracted_entities={
                    "filter_action": "expand",
                    "uses_context_reference": True
                }
            )

        # Check for modification triggers
        mod_score = sum(1 for trigger in self.MODIFICATION_TRIGGERS if trigger in message_lower)

        if mod_score > 0:
            # Determine modification type
            if any(t in message_lower for t in ["bazlı", "bazında", "aylık", "günlük"]):
                return IntentClassificationResult(
                    intent_type=IntentType.MODIFY_AGGREGATION,
                    confidence=0.8,
                    extracted_entities={}
                )
            elif any(t in message_lower for t in ["sırala", "büyükten", "küçükten"]):
                return IntentClassificationResult(
                    intent_type=IntentType.MODIFY_ORDER,
                    confidence=0.8,
                    extracted_entities={}
                )
            else:
                filter_action = "remove" if any(t in message_lower for t in ["hariç", "çıkar", "kaldır"]) else "add"
                return IntentClassificationResult(
                    intent_type=IntentType.MODIFY_FILTER,
                    confidence=0.75,
                    extracted_entities={"filter_action": filter_action}
                )

        # Check for rollback
        if any(t in message_lower for t in ["geri", "önceki", "iptal", "undo"]):
            return IntentClassificationResult(
                intent_type=IntentType.ROLLBACK,
                confidence=0.9,
                extracted_entities={}
            )

        # Check for visualization change
        if any(t in message_lower for t in ["grafik", "chart", "bar", "pasta", "line"]):
            return IntentClassificationResult(
                intent_type=IntentType.VISUALIZE,
                confidence=0.85,
                extracted_entities={}
            )

        # Default: new query
        return IntentClassificationResult(
            intent_type=IntentType.NEW_QUERY,
            confidence=0.7,
            extracted_entities={}
        )

    def _get_tool_guidance(self, intent_type: IntentType) -> str:
        """
        Get tool selection guidance based on intent.

        Args:
            intent_type: Detected intent

        Returns:
            Guidance text for agent
        """
        guidance_map = {
            IntentType.NEW_QUERY: "Use text2sql_tool for new query. No context needed.",
            IntentType.MODIFY_FILTER: "Use text2sql_tool with existing context. This is a modification request.",
            IntentType.MODIFY_AGGREGATION: "Use text2sql_tool with context to change grouping/aggregation.",
            IntentType.MODIFY_ORDER: "Use text2sql_tool with context to change ordering.",
            IntentType.MODIFY_COLUMNS: "Use text2sql_tool with context to add/remove columns.",
            IntentType.VISUALIZE: "Keep same SQL, only use visualization_tool.",
            IntentType.ROLLBACK: "Use rollback_tool to restore previous query.",
            IntentType.CLARIFY: "Ask user for clarification before proceeding.",
        }

        return guidance_map.get(intent_type, "Determine appropriate tool based on user request.")
