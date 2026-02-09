"""
Response Generator - Natural Language Response Generation

Replaces template-based responses with natural, conversational LLM-generated responses.
Highlights business insights and suggests follow-up actions.

Features:
- LLM generates conversational responses
- Highlights business insights
- Suggests follow-up actions
- Natural, helpful tone
- Template-based fallback for errors/simple cases

Usage:
    generator = ResponseGenerator(llm)
    response = await generator.generate_response(
        user_query="Show me sales",
        data_results=results,
        business_context=context,
        visualization_info=viz_decision
    )
"""

import logging
from typing import Dict, Any, Optional, List

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from .state import BusinessContext
from .prompts import (
    RESPONSE_GENERATION_SYSTEM,
    RESPONSE_GENERATION_TEMPLATE,
    format_data_sample,
    format_business_insights,
    format_visualization_info
)
from .semantic_cache import SemanticCache

logger = logging.getLogger(__name__)


# =============================================================================
# RESPONSE GENERATOR
# =============================================================================

class ResponseGenerator:
    """
    Natural language response generator.

    Generates conversational, insight-rich responses instead of templates.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        use_llm: bool = True,
        semantic_cache: Optional[SemanticCache] = None
    ):
        """
        Initialize response generator.

        Args:
            llm: Language model for response generation
            use_llm: Use LLM (vs template fallback)
            semantic_cache: Optional semantic cache
        """
        self.llm = llm
        self.use_llm = use_llm
        self.semantic_cache = semantic_cache

        # Create prompt template
        self.prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=RESPONSE_GENERATION_SYSTEM),
            HumanMessage(content=RESPONSE_GENERATION_TEMPLATE)
        ])

        logger.info(f"[RESPONSE_GEN] Initialized (use_llm={use_llm})")

    async def generate_response(
        self,
        user_query: str,
        data_results: Optional[List[Dict[str, Any]]] = None,
        business_context: Optional[BusinessContext] = None,
        visualization_info: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        no_records_message: Optional[str] = None
    ) -> str:
        """
        Generate natural language response.

        Args:
            user_query: User's query
            data_results: Query results
            business_context: Business context with insights
            visualization_info: Visualization decision
            error: Error message (if any)
            no_records_message: No records message (if any)

        Returns:
            Natural language response (Markdown formatted)
        """
        logger.info(f"[RESPONSE_GEN] Generating response for: {user_query[:50]}...")

        # Handle errors (template fallback)
        if error:
            return self._error_response(error)

        # Handle no records (template fallback)
        if no_records_message:
            return self._no_records_response(no_records_message)

        # Handle empty results (template)
        if not data_results or len(data_results) == 0:
            return self._empty_response(user_query)

        # LLM-generated response (if enabled and results exist)
        if self.use_llm and data_results:
            # Only use LLM if we have business context or viz info to make it worthwhile
            # Otherwise, template response is sufficient
            has_insights = business_context and business_context.get("key_insights")
            has_viz_info = visualization_info and visualization_info.get("output_type")

            if has_insights or has_viz_info:
                return await self._llm_generate(
                    user_query=user_query,
                    data_results=data_results,
                    business_context=business_context,
                    visualization_info=visualization_info
                )
            else:
                # No insights/viz info, use template (faster, cheaper)
                logger.info("[RESPONSE_GEN] No insights/viz info, using template response")
                return self._template_response(
                    user_query=user_query,
                    data_results=data_results,
                    business_context=business_context,
                    visualization_info=visualization_info
                )

        # Template fallback
        return self._template_response(
            user_query=user_query,
            data_results=data_results,
            business_context=business_context,
            visualization_info=visualization_info
        )

    # -------------------------------------------------------------------------
    # LLM GENERATION
    # -------------------------------------------------------------------------

    async def _llm_generate(
        self,
        user_query: str,
        data_results: List[Dict[str, Any]],
        business_context: Optional[BusinessContext],
        visualization_info: Optional[Dict[str, Any]]
    ) -> str:
        """
        LLM-powered response generation.

        Args:
            user_query: User query
            data_results: Results
            business_context: Business context
            visualization_info: Viz info

        Returns:
            Natural language response
        """
        # Format data summary
        data_summary = self._format_data_summary(data_results)

        # Format business insights
        insights_str = format_business_insights(business_context)
        if not insights_str:
            insights_str = "(Business insights yok)"

        # Format visualization info
        viz_str = format_visualization_info(visualization_info)
        if not viz_str:
            viz_str = "(Görselleştirme bilgisi yok)"

        # Prepare prompt
        prompt_vars = {
            "user_query": user_query,
            "data_summary": data_summary,
            "business_insights": insights_str,
            "visualization_info": viz_str
        }

        # Call LLM (with cache if available)
        if self.semantic_cache:
            cache_key = f"{user_query}::{data_summary[:100]}"
            response = await self.semantic_cache.get_or_compute(
                query=cache_key,
                compute_fn=lambda: self._call_llm(prompt_vars)
            )
        else:
            response = await self._call_llm(prompt_vars)

        logger.info(f"[RESPONSE_GEN] Generated {len(response)} chars")

        return response

    async def _call_llm(self, prompt_vars: Dict[str, str]) -> str:
        """Call LLM with prompt."""
        try:
            messages = self.prompt.format_messages(**prompt_vars)
            response = await self.llm.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"[RESPONSE_GEN] LLM call failed: {e}")
            # Fallback to template
            return self._simple_template(prompt_vars)

    # -------------------------------------------------------------------------
    # TEMPLATE FALLBACK
    # -------------------------------------------------------------------------

    def _template_response(
        self,
        user_query: str,
        data_results: List[Dict[str, Any]],
        business_context: Optional[BusinessContext],
        visualization_info: Optional[Dict[str, Any]]
    ) -> str:
        """
        Template-based response (fallback).

        Args:
            user_query: User query
            data_results: Results
            business_context: Business context
            visualization_info: Viz info

        Returns:
            Template response
        """
        parts = ["📊 **Rapor Sonucu**\n"]

        # Data count
        parts.append(f"• **Sonuç sayısı:** {len(data_results)} kayıt\n")

        # Key insights
        if business_context:
            insights = business_context.get("key_insights", [])
            if insights:
                parts.append("\n**Önemli Bulgular:**")
                for insight in insights[:3]:
                    parts.append(f"• {insight}")
                parts.append("")

        # Visualization
        if visualization_info:
            output_type = visualization_info.get("output_type", "")
            parts.append(f"• **Format:** {output_type}\n")

        # Follow-ups
        if business_context:
            followups = business_context.get("suggested_follow_ups", [])
            if followups:
                parts.append("\n**İlgili Sorular:**")
                for followup in followups[:2]:
                    parts.append(f"• {followup}")

        return "\n".join(parts)

    def _error_response(self, error: str) -> str:
        """Error response template."""
        return f"❌ **Hata**\n\n{error}\n\nLütfen sorgunuzu yeniden ifade edin."

    def _no_records_response(self, message: str) -> str:
        """No records response template."""
        return f"ℹ️ **Sonuç Bulunamadı**\n\n{message}\n\n**Öneriler:**\n• Filtre kriterlerini genişletin\n• Farklı bir zaman aralığı deneyin\n• Sorgunuzu yeniden ifade edin"

    def _empty_response(self, user_query: str) -> str:
        """Empty results response."""
        return "ℹ️ **Sonuç Bulunamadı**\n\nSorgunuz için veri bulunamadı. Lütfen farklı filtreler veya kriterler deneyin."

    def _simple_template(self, prompt_vars: Dict[str, str]) -> str:
        """Simple template when LLM fails."""
        data_summary = prompt_vars.get("data_summary", "")
        return f"📊 **Rapor Sonucu**\n\n{data_summary}"

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------

    def _format_data_summary(self, data_results: List[Dict[str, Any]]) -> str:
        """
        Format data summary for prompt.

        Args:
            data_results: Results

        Returns:
            Summary string
        """
        if not data_results:
            return "Sonuç yok"

        parts = []

        # Row count
        parts.append(f"Toplam {len(data_results)} kayıt")

        # Column names
        if data_results:
            columns = list(data_results[0].keys())
            parts.append(f"Kolonlar: {', '.join(columns)}")

        # Sample data (first 5 rows)
        sample = format_data_sample(data_results, max_rows=5)
        parts.append(f"\nÖrnek veri:\n{sample}")

        return "\n".join(parts)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_response_with_insights(
    base_response: str,
    business_context: Optional[BusinessContext]
) -> str:
    """
    Add business insights to existing response.

    Args:
        base_response: Base response text
        business_context: Business context

    Returns:
        Enhanced response with insights
    """
    if not business_context:
        return base_response

    parts = [base_response]

    # Add insights
    insights = business_context.get("key_insights", [])
    if insights:
        parts.append("\n**Önemli Bulgular:**")
        for insight in insights:
            parts.append(f"• {insight}")

    # Add follow-ups
    followups = business_context.get("suggested_follow_ups", [])
    if followups:
        parts.append("\n**İlgili Sorular:**")
        for followup in followups:
            parts.append(f"• {followup}")

    return "\n".join(parts)


def create_simple_response(
    data_count: int,
    output_type: str,
    key_insight: Optional[str] = None
) -> str:
    """
    Create simple response without LLM.

    Args:
        data_count: Number of results
        output_type: Output format type
        key_insight: Optional key insight

    Returns:
        Simple response text
    """
    parts = ["📊 **Rapor Sonucu**\n"]

    parts.append(f"• **Sonuç sayısı:** {data_count} kayıt")
    parts.append(f"• **Format:** {output_type}")

    if key_insight:
        parts.append(f"\n**Bulgu:** {key_insight}")

    return "\n".join(parts)


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_response_generator(
    llm: BaseChatModel,
    use_llm: bool = True,
    semantic_cache: Optional[SemanticCache] = None
) -> ResponseGenerator:
    """
    Factory function to create ResponseGenerator.

    Args:
        llm: Language model
        use_llm: Use LLM generation
        semantic_cache: Optional semantic cache

    Returns:
        ResponseGenerator instance
    """
    return ResponseGenerator(
        llm=llm,
        use_llm=use_llm,
        semantic_cache=semantic_cache
    )
