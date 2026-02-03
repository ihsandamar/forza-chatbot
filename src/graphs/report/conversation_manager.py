"""
Conversation Manager - LLM-Powered Intent Understanding

Enhances IntentClassifier with full LLM-powered conversation management.
Provides business context reasoning, clarification generation, and natural flow.

Features:
- LLM-powered intent understanding (not just classification)
- Business context reasoning layer
- Clarification question generation
- Natural conversation flow management
- Feature flag support for gradual rollout
- Reuses existing IntentClassifier as foundation

Usage:
    manager = ConversationManager(llm, enable_llm_reasoning=True)
    intent = await manager.understand_intent(
        user_message="Show me sales",
        active_context=context,
        conversation_history=messages
    )
"""

import logging
import json
from typing import Optional, List, Dict, Any
from datetime import datetime

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from .state import ActiveQueryContext, BusinessContext
from .intent import IntentClassifier, SimpleIntentClassifier, IntentClassification, IntentType
from .prompts import (
    INTENT_UNDERSTANDING_SYSTEM,
    INTENT_UNDERSTANDING_TEMPLATE,
    format_context_info
)
from .context_window import ContextWindow, format_context_for_llm
from .semantic_cache import SemanticCache

logger = logging.getLogger(__name__)


# =============================================================================
# CONVERSATION INTENT (Enhanced)
# =============================================================================

class ConversationIntent(IntentClassification):
    """
    Enhanced intent classification with business reasoning.

    Extends IntentClassification with:
    - Business context understanding
    - Reasoning trace
    - Conversation flow awareness
    """

    def __init__(
        self,
        intent_type: IntentType,
        confidence: float,
        requires_clarification: bool,
        clarification_question: Optional[str],
        clarification_options: Optional[List[str]],
        extracted_entities: Dict[str, Any],
        reasoning: Optional[str] = None,
        business_context_aware: bool = False
    ):
        super().__init__(
            intent_type=intent_type,
            confidence=confidence,
            requires_clarification=requires_clarification,
            clarification_question=clarification_question,
            clarification_options=clarification_options,
            extracted_entities=extracted_entities
        )
        self.reasoning = reasoning
        self.business_context_aware = business_context_aware


# =============================================================================
# CONVERSATION MANAGER
# =============================================================================

class ConversationManager:
    """
    LLM-powered conversation management.

    Enhances IntentClassifier with:
    - Full LLM intent understanding (not just classification)
    - Business context reasoning
    - Smart clarification generation
    - Conversation flow management
    """

    def __init__(
        self,
        llm: BaseChatModel,
        enable_llm_reasoning: bool = True,
        use_simple_classifier_threshold: float = 0.85,
        semantic_cache: Optional[SemanticCache] = None
    ):
        """
        Initialize conversation manager.

        Args:
            llm: Language model for intent understanding
            enable_llm_reasoning: Enable LLM reasoning (vs rule-based)
            use_simple_classifier_threshold: Use simple classifier if confidence above this
            semantic_cache: Optional semantic cache
        """
        self.llm = llm
        self.enable_llm_reasoning = enable_llm_reasoning
        self.simple_threshold = use_simple_classifier_threshold
        self.semantic_cache = semantic_cache

        # Create classifiers (reuse existing)
        self.intent_classifier = IntentClassifier(llm)
        self.simple_classifier = SimpleIntentClassifier()

        # Create context window manager
        self.context_window = ContextWindow(max_tokens=2000)

        # Create prompt template
        self.prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=INTENT_UNDERSTANDING_SYSTEM),
            HumanMessage(content=INTENT_UNDERSTANDING_TEMPLATE)
        ])

        logger.info(f"[CONVERSATION] Initialized (LLM reasoning: {enable_llm_reasoning})")

    async def understand_intent(
        self,
        user_message: str,
        active_context: Optional[ActiveQueryContext] = None,
        conversation_history: Optional[List[BaseMessage]] = None,
        business_context: Optional[BusinessContext] = None
    ) -> ConversationIntent:
        """
        Understand user intent with full context awareness.

        Args:
            user_message: User's message
            active_context: Active query context (SQL state)
            conversation_history: Full conversation history
            business_context: Business context (goals, insights)

        Returns:
            ConversationIntent with reasoning
        """
        logger.info(f"[CONVERSATION] Understanding intent: {user_message[:50]}...")

        # Fast path: Try simple classifier first
        simple_result = self.simple_classifier.classify(
            user_message=user_message,
            has_active_context=active_context is not None
        )

        # If simple classifier is confident enough and no active context, use it
        if (simple_result.confidence >= self.simple_threshold and
            not active_context and
            not self.enable_llm_reasoning):
            logger.info(f"[CONVERSATION] Simple classifier used (confidence: {simple_result.confidence:.2f})")
            return self._convert_to_conversation_intent(simple_result, reasoning="Fast path: Simple classifier")

        # If active context exists, ALWAYS use LLM (better context understanding)
        if active_context or self.enable_llm_reasoning:
            logger.info("[CONVERSATION] Using LLM-powered intent understanding")
            return await self._llm_understand(
                user_message=user_message,
                active_context=active_context,
                conversation_history=conversation_history or [],
                business_context=business_context
            )

        # Fallback: Use existing IntentClassifier
        logger.info("[CONVERSATION] Using IntentClassifier (fallback)")
        result = await self.intent_classifier.classify_async(
            user_message=user_message,
            active_context=active_context,
            conversation_history=conversation_history or []
        )

        return self._convert_to_conversation_intent(result, reasoning="Fallback: IntentClassifier")

    async def generate_clarification(
        self,
        user_message: str,
        ambiguity_type: str,
        options: List[str],
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate smart clarification question.

        Args:
            user_message: User's message
            ambiguity_type: Type of ambiguity (table, column, value, etc.)
            options: Available options
            context: Additional context

        Returns:
            Clarification dict with question and options
        """
        logger.info(f"[CONVERSATION] Generating clarification for: {ambiguity_type}")

        if not self.enable_llm_reasoning:
            # Simple template-based clarification
            return self._simple_clarification(ambiguity_type, options)

        # LLM-generated clarification
        from .prompts import CLARIFICATION_GENERATION_SYSTEM, CLARIFICATION_GENERATION_TEMPLATE

        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=CLARIFICATION_GENERATION_SYSTEM),
            HumanMessage(content=CLARIFICATION_GENERATION_TEMPLATE)
        ])

        messages = prompt.format_messages(
            user_message=user_message,
            ambiguity_type=ambiguity_type,
            options=options,
            context=context or ""
        )

        try:
            response = await self.llm.ainvoke(messages)
            clarification = self._parse_clarification(response.content, options)
            return clarification
        except Exception as e:
            logger.error(f"[CONVERSATION] Clarification generation error: {e}")
            return self._simple_clarification(ambiguity_type, options)

    # -------------------------------------------------------------------------
    # LLM-POWERED UNDERSTANDING
    # -------------------------------------------------------------------------

    async def _llm_understand(
        self,
        user_message: str,
        active_context: Optional[ActiveQueryContext],
        conversation_history: List[BaseMessage],
        business_context: Optional[BusinessContext]
    ) -> ConversationIntent:
        """
        LLM-powered intent understanding with business context.

        Args:
            user_message: User message
            active_context: Active query context
            conversation_history: Conversation history
            business_context: Business context

        Returns:
            ConversationIntent with reasoning
        """
        # Get relevant context (smart windowing)
        relevant_history = self.context_window.get_relevant_context(
            current_query=user_message,
            full_history=conversation_history,
            active_context=active_context
        )

        # Format context info
        context_info = format_context_info(active_context, relevant_history)

        # Prepare prompt
        prompt_vars = {
            "user_message": user_message,
            "context_info": context_info
        }

        # Call LLM (with cache if available)
        if self.semantic_cache:
            cache_key = f"{user_message}::{context_info[:100]}"
            intent_json = await self.semantic_cache.get_or_compute(
                query=cache_key,
                compute_fn=lambda: self._call_llm(prompt_vars)
            )
        else:
            intent_json = await self._call_llm(prompt_vars)

        # Parse result
        intent = self._parse_llm_intent(intent_json, user_message)

        logger.info(f"[CONVERSATION] Intent: {intent.intent_type}, Confidence: {intent.confidence:.2f}")

        return intent

    async def _call_llm(self, prompt_vars: Dict[str, str]) -> str:
        """Call LLM with prompt."""
        try:
            messages = self.prompt.format_messages(**prompt_vars)
            response = await self.llm.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"[CONVERSATION] LLM call failed: {e}")
            return "{}"

    def _parse_llm_intent(self, llm_response: str, user_message: str) -> ConversationIntent:
        """Parse LLM response into ConversationIntent."""
        try:
            # Extract JSON from response
            json_str = llm_response
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)

            # Parse intent type
            intent_type_str = data.get("intent_type", "new_query")
            try:
                intent_type = IntentType(intent_type_str)
            except ValueError:
                intent_type = IntentType.NEW_QUERY

            return ConversationIntent(
                intent_type=intent_type,
                confidence=float(data.get("confidence", 0.7)),
                requires_clarification=bool(data.get("requires_clarification", False)),
                clarification_question=data.get("clarification_question"),
                clarification_options=data.get("clarification_options"),
                extracted_entities=data.get("extracted_entities", {}),
                reasoning=data.get("reasoning", ""),
                business_context_aware=True
            )

        except Exception as e:
            logger.error(f"[CONVERSATION] Parse error: {e}")
            # Fallback: new_query
            return ConversationIntent(
                intent_type=IntentType.NEW_QUERY,
                confidence=0.5,
                requires_clarification=False,
                clarification_question=None,
                clarification_options=None,
                extracted_entities={},
                reasoning=f"Parse error: {str(e)}",
                business_context_aware=False
            )

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------

    def _convert_to_conversation_intent(
        self,
        intent: IntentClassification,
        reasoning: str
    ) -> ConversationIntent:
        """Convert IntentClassification to ConversationIntent."""
        return ConversationIntent(
            intent_type=intent.intent_type,
            confidence=intent.confidence,
            requires_clarification=intent.requires_clarification,
            clarification_question=intent.clarification_question,
            clarification_options=intent.clarification_options,
            extracted_entities=intent.extracted_entities,
            reasoning=reasoning,
            business_context_aware=False
        )

    def _simple_clarification(self, ambiguity_type: str, options: List[str]) -> Dict[str, Any]:
        """Generate simple template-based clarification."""
        questions = {
            "table": "Hangi tablodan veri çekmek istersiniz?",
            "column": "Hangi kolonları görmek istersiniz?",
            "value": "Hangi değer için filtreleme yapalım?",
            "date": "Hangi zaman aralığını görmek istersiniz?"
        }

        question = questions.get(ambiguity_type, "Lütfen seçim yapın:")

        return {
            "question": question,
            "options": options,
            "context": None
        }

    def _parse_clarification(self, llm_response: str, fallback_options: List[str]) -> Dict[str, Any]:
        """Parse LLM clarification response."""
        try:
            json_str = llm_response
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)

            return {
                "question": data.get("question", "Lütfen seçim yapın:"),
                "options": data.get("options", fallback_options),
                "context": data.get("context")
            }

        except Exception as e:
            logger.error(f"[CONVERSATION] Clarification parse error: {e}")
            return {
                "question": "Lütfen seçim yapın:",
                "options": fallback_options,
                "context": None
            }


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_conversation_manager(
    llm: BaseChatModel,
    enable_llm_reasoning: bool = True,
    semantic_cache: Optional[SemanticCache] = None
) -> ConversationManager:
    """
    Factory function to create ConversationManager.

    Args:
        llm: Language model
        enable_llm_reasoning: Enable LLM-powered reasoning
        semantic_cache: Optional semantic cache

    Returns:
        ConversationManager instance
    """
    return ConversationManager(
        llm=llm,
        enable_llm_reasoning=enable_llm_reasoning,
        semantic_cache=semantic_cache
    )
