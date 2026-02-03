"""
Business Context Tracker

Tracks business-level insights and user goals throughout conversation.
Extracts meaningful business information beyond technical SQL state.

Features:
- Business question understanding
- Key insights extraction from data
- Natural language data summaries
- Smart follow-up question suggestions
- User goal inference

Usage:
    tracker = BusinessContextTracker(llm)
    business_context = await tracker.extract_insights(
        user_query="Show me sales by city",
        data_results=results,
        active_context=context
    )
"""

import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from .state import BusinessContext
from .prompts import (
    BUSINESS_INSIGHTS_SYSTEM,
    BUSINESS_INSIGHTS_TEMPLATE,
    format_data_sample
)
from .semantic_cache import SemanticCache

logger = logging.getLogger(__name__)


# =============================================================================
# BUSINESS CONTEXT TRACKER
# =============================================================================

class BusinessContextTracker:
    """
    Tracks business context and extracts insights from data.

    Maintains understanding of:
    - What business question user is trying to answer
    - Key insights from results
    - Natural language summaries
    - Suggested next questions
    - Inferred user goals
    """

    def __init__(
        self,
        llm: BaseChatModel,
        semantic_cache: Optional[SemanticCache] = None
    ):
        """
        Initialize business context tracker.

        Args:
            llm: Language model for insight extraction
            semantic_cache: Optional semantic cache for LLM calls
        """
        self.llm = llm
        self.semantic_cache = semantic_cache

        # Create prompt template
        self.prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=BUSINESS_INSIGHTS_SYSTEM),
            HumanMessage(content=BUSINESS_INSIGHTS_TEMPLATE)
        ])

        logger.info("[BUSINESS_CONTEXT] Initialized tracker")

    async def extract_insights(
        self,
        user_query: str,
        data_results: List[Dict[str, Any]],
        active_context: Optional[Dict[str, Any]] = None,
        previous_business_context: Optional[BusinessContext] = None
    ) -> BusinessContext:
        """
        Extract business insights from query and results.

        Args:
            user_query: User's business question
            data_results: Query results (data)
            active_context: Active query context (SQL, filters, etc.)
            previous_business_context: Previous business context (for continuity)

        Returns:
            BusinessContext with insights
        """
        logger.info(f"[BUSINESS_CONTEXT] Extracting insights for: {user_query[:50]}...")

        # Handle empty results
        if not data_results or len(data_results) == 0:
            return self._create_empty_context(user_query)

        # Format data sample for LLM
        data_sample_str = format_data_sample(data_results, max_rows=10)

        # Build business question (maintain continuity)
        business_question = self._build_business_question(
            user_query,
            previous_business_context
        )

        # Prepare prompt
        prompt_vars = {
            "business_question": business_question,
            "data_sample": data_sample_str
        }

        # Call LLM (with cache if available)
        if self.semantic_cache:
            cache_key = f"{user_query}::{len(data_results)}"
            insights_json = await self.semantic_cache.get_or_compute(
                query=cache_key,
                compute_fn=lambda: self._call_llm(prompt_vars)
            )
        else:
            insights_json = await self._call_llm(prompt_vars)

        # Parse and validate
        business_context = self._parse_insights(insights_json, user_query)

        logger.info(f"[BUSINESS_CONTEXT] Extracted {len(business_context['key_insights'])} insights")

        return business_context

    async def update_context(
        self,
        current_context: BusinessContext,
        new_query: str,
        new_results: List[Dict[str, Any]]
    ) -> BusinessContext:
        """
        Update business context with new query/results.

        Args:
            current_context: Current business context
            new_query: New user query
            new_results: New results

        Returns:
            Updated business context
        """
        # Extract new insights
        new_context = await self.extract_insights(
            user_query=new_query,
            data_results=new_results,
            previous_business_context=current_context
        )

        # Merge insights (keep unique, prioritize new)
        merged_insights = list(dict.fromkeys(
            new_context["key_insights"] + current_context.get("key_insights", [])
        ))[:5]  # Keep top 5

        # Merge follow-ups (keep unique)
        merged_followups = list(dict.fromkeys(
            new_context["suggested_follow_ups"] + current_context.get("suggested_follow_ups", [])
        ))[:3]  # Keep top 3

        # Update goal (prefer new if set)
        updated_goal = new_context["user_goal"] or current_context.get("user_goal")

        return BusinessContext(
            business_question=new_context["business_question"],
            key_insights=merged_insights,
            data_summary=new_context["data_summary"],
            suggested_follow_ups=merged_followups,
            user_goal=updated_goal
        )

    # -------------------------------------------------------------------------
    # INTERNAL METHODS
    # -------------------------------------------------------------------------

    async def _call_llm(self, prompt_vars: Dict[str, str]) -> str:
        """Call LLM with prompt."""
        try:
            messages = self.prompt.format_messages(**prompt_vars)
            response = await self.llm.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"[BUSINESS_CONTEXT] LLM call failed: {e}")
            return "{}"

    def _parse_insights(self, llm_response: str, user_query: str) -> BusinessContext:
        """Parse LLM response into BusinessContext."""
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_str = llm_response
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)

            return BusinessContext(
                business_question=data.get("business_question", user_query),
                key_insights=data.get("key_insights", []),
                data_summary=data.get("data_summary", ""),
                suggested_follow_ups=data.get("suggested_follow_ups", []),
                user_goal=data.get("user_goal")
            )

        except Exception as e:
            logger.error(f"[BUSINESS_CONTEXT] Parse error: {e}")
            # Fallback: create basic context
            return BusinessContext(
                business_question=user_query,
                key_insights=[],
                data_summary=f"Sorgu sonucu: {len([1])} kayıt",
                suggested_follow_ups=[],
                user_goal=None
            )

    def _create_empty_context(self, user_query: str) -> BusinessContext:
        """Create empty business context for no results."""
        return BusinessContext(
            business_question=user_query,
            key_insights=["Sonuç bulunamadı"],
            data_summary="Sorgu sonucu boş döndü",
            suggested_follow_ups=["Filtre kriterlerini genişletin", "Farklı bir zaman aralığı deneyin"],
            user_goal=None
        )

    def _build_business_question(
        self,
        user_query: str,
        previous_context: Optional[BusinessContext]
    ) -> str:
        """
        Build business question maintaining context continuity.

        Args:
            user_query: Current query
            previous_context: Previous business context

        Returns:
            Business question string
        """
        # If previous context exists and query is modification, combine
        if previous_context and self._is_modification_query(user_query):
            base = previous_context.get("business_question", "")
            return f"{base} (modifiye: {user_query})"

        # Otherwise, use current query as-is
        return user_query

    def _is_modification_query(self, query: str) -> bool:
        """Check if query is a modification of previous query."""
        modification_keywords = [
            "sadece", "only", "ekle", "add", "çıkar", "remove",
            "değiştir", "change", "göster", "show", "filtrele", "filter",
            "dahil", "include", "hariç", "exclude"
        ]

        query_lower = query.lower()
        return any(kw in query_lower for kw in modification_keywords)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_business_context(business_context: Optional[BusinessContext]) -> str:
    """
    Format business context for display.

    Args:
        business_context: Business context to format

    Returns:
        Formatted string
    """
    if not business_context:
        return ""

    parts = []

    # Business question
    question = business_context.get("business_question", "")
    if question:
        parts.append(f"**Soru:** {question}")

    # Key insights
    insights = business_context.get("key_insights", [])
    if insights:
        parts.append("\n**Önemli Bulgular:**")
        for insight in insights:
            parts.append(f"• {insight}")

    # Data summary
    summary = business_context.get("data_summary", "")
    if summary:
        parts.append(f"\n**Özet:** {summary}")

    # Follow-ups
    followups = business_context.get("suggested_follow_ups", [])
    if followups:
        parts.append("\n**İlgili Sorular:**")
        for followup in followups:
            parts.append(f"• {followup}")

    return "\n".join(parts)


def get_key_insights(business_context: Optional[BusinessContext]) -> List[str]:
    """
    Get key insights from business context.

    Args:
        business_context: Business context

    Returns:
        List of insights
    """
    if not business_context:
        return []

    return business_context.get("key_insights", [])


def get_follow_up_questions(business_context: Optional[BusinessContext]) -> List[str]:
    """
    Get suggested follow-up questions.

    Args:
        business_context: Business context

    Returns:
        List of follow-up questions
    """
    if not business_context:
        return []

    return business_context.get("suggested_follow_ups", [])
