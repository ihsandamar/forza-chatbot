"""
Report Interpreter - LLM-Assisted Result Interpretation

Replaces rule-based visualization decision with LLM reasoning.
Analyzes data + user intent to decide best presentation format.

Features:
- LLM analyzes data and user intent
- Decides presentation format with reasoning
- Suggests alternatives
- Generates data narratives
- Rule-based fallback for backward compatibility

Usage:
    interpreter = ReportInterpreter(llm)
    interpretation = await interpreter.interpret_results(
        user_query="Show me sales by city",
        data_results=results,
        active_context=context
    )
"""

import logging
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from .prompts import (
    REPORT_INTERPRETATION_SYSTEM,
    REPORT_INTERPRETATION_TEMPLATE,
    format_data_sample
)
from .semantic_cache import SemanticCache

logger = logging.getLogger(__name__)


# =============================================================================
# INTERPRETATION RESULT
# =============================================================================

@dataclass
class InterpretationResult:
    """Result of report interpretation."""

    needs_graph: bool                       # True if chart/graph needed
    output_type: str                        # "single_value", "simple_list", "table", "bar_chart", etc.
    chart_type: Optional[str]               # Chart type if needs_graph=True
    reason: str                             # Reasoning for decision
    alternatives: List[str]                 # Alternative presentation formats
    key_insight: Optional[str]              # Key insight from data
    reasoning: str                          # Full LLM reasoning trace

    def dict(self) -> Dict[str, Any]:
        """Convert to dict for state storage."""
        return {
            "needs_graph": self.needs_graph,
            "output_type": self.output_type,
            "chart_type": self.chart_type,
            "reason": self.reason,
            "alternatives": self.alternatives,
            "key_insight": self.key_insight
        }


# =============================================================================
# REPORT INTERPRETER
# =============================================================================

class ReportInterpreter:
    """
    LLM-assisted report interpretation.

    Analyzes query results and decides best presentation format.
    Replaces simple rule-based logic with intelligent reasoning.
    """

    def __init__(
        self,
        llm: BaseChatModel,
        use_llm: bool = True,
        semantic_cache: Optional[SemanticCache] = None
    ):
        """
        Initialize report interpreter.

        Args:
            llm: Language model for interpretation
            use_llm: Use LLM (vs rule-based fallback)
            semantic_cache: Optional semantic cache
        """
        self.llm = llm
        self.use_llm = use_llm
        self.semantic_cache = semantic_cache

        # Create prompt template
        self.prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=REPORT_INTERPRETATION_SYSTEM),
            HumanMessage(content=REPORT_INTERPRETATION_TEMPLATE)
        ])

        logger.info(f"[INTERPRETER] Initialized (use_llm={use_llm})")

    async def interpret_results(
        self,
        user_query: str,
        data_results: List[Dict[str, Any]],
        active_context: Optional[Dict[str, Any]] = None
    ) -> InterpretationResult:
        """
        Interpret query results and decide presentation format.

        Args:
            user_query: User's query
            data_results: Query results
            active_context: Active query context

        Returns:
            InterpretationResult with decision and reasoning
        """
        logger.info(f"[INTERPRETER] Interpreting {len(data_results)} results")

        # Quick rule-based decisions (fast path)
        quick_result = self._quick_rules(user_query, data_results)
        if quick_result:
            logger.info(f"[INTERPRETER] Quick rule applied: {quick_result.output_type}")
            return quick_result

        # LLM interpretation (if enabled)
        if self.use_llm:
            return await self._llm_interpret(user_query, data_results, active_context)

        # Fallback: rule-based
        return self._rule_based_fallback(user_query, data_results)

    # -------------------------------------------------------------------------
    # QUICK RULES (Fast Path)
    # -------------------------------------------------------------------------

    def _quick_rules(
        self,
        user_query: str,
        data_results: List[Dict[str, Any]]
    ) -> Optional[InterpretationResult]:
        """
        Apply quick rule-based decisions.

        Args:
            user_query: User query
            data_results: Results

        Returns:
            InterpretationResult or None if no quick rule applies
        """
        # Empty results
        if not data_results or len(data_results) == 0:
            return InterpretationResult(
                needs_graph=False,
                output_type="table",
                chart_type=None,
                reason="Sonuç yok",
                alternatives=[],
                key_insight=None,
                reasoning="Quick rule: Empty results"
            )

        # Single value
        if len(data_results) == 1 and len(data_results[0].keys()) == 1:
            return InterpretationResult(
                needs_graph=False,
                output_type="single_value",
                chart_type=None,
                reason="Tek değer sonucu",
                alternatives=["table"],
                key_insight=None,
                reasoning="Quick rule: Single value"
            )

        # Explicit chart request
        user_query_lower = user_query.lower()

        chart_keywords = {
            "bar": ["çubuk", "bar", "막대"],
            "line": ["çizgi", "line", "trend"],
            "pie": ["pasta", "pie", "daire", "oran"],
            "scatter": ["scatter", "dağılım"],
            "sunburst": ["sunburst", "hiyerarşik"],
            "treemap": ["treemap", "ağaç"]
        }

        for chart_type, keywords in chart_keywords.items():
            if any(kw in user_query_lower for kw in keywords):
                return InterpretationResult(
                    needs_graph=True,
                    output_type=f"{chart_type}_chart",
                    chart_type=f"{chart_type}_chart",
                    reason=f"Kullanıcı {chart_type} chart istedi",
                    alternatives=["table", "simple_list"],
                    key_insight=None,
                    reasoning=f"Quick rule: Explicit {chart_type} request"
                )

        # No quick rule applies
        return None

    # -------------------------------------------------------------------------
    # LLM INTERPRETATION
    # -------------------------------------------------------------------------

    async def _llm_interpret(
        self,
        user_query: str,
        data_results: List[Dict[str, Any]],
        active_context: Optional[Dict[str, Any]]
    ) -> InterpretationResult:
        """
        LLM-powered interpretation.

        Args:
            user_query: User query
            data_results: Results
            active_context: Active context

        Returns:
            InterpretationResult with LLM reasoning
        """
        # Format data sample
        data_sample_str = format_data_sample(data_results, max_rows=10)

        # Prepare prompt
        prompt_vars = {
            "user_query": user_query,
            "data_sample": data_sample_str,
            "row_count": len(data_results)
        }

        # Call LLM (with cache if available)
        if self.semantic_cache:
            cache_key = f"{user_query}::{len(data_results)}::{data_sample_str[:100]}"
            interpretation_json = await self.semantic_cache.get_or_compute(
                query=cache_key,
                compute_fn=lambda: self._call_llm(prompt_vars)
            )
        else:
            interpretation_json = await self._call_llm(prompt_vars)

        # Parse result
        result = self._parse_interpretation(interpretation_json)

        logger.info(f"[INTERPRETER] LLM decision: {result.output_type} (needs_graph={result.needs_graph})")

        return result

    async def _call_llm(self, prompt_vars: Dict[str, Any]) -> str:
        """Call LLM with prompt."""
        try:
            messages = self.prompt.format_messages(**prompt_vars)
            response = await self.llm.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"[INTERPRETER] LLM call failed: {e}")
            return "{}"

    def _parse_interpretation(self, llm_response: str) -> InterpretationResult:
        """Parse LLM response into InterpretationResult."""
        try:
            # Extract JSON from response
            json_str = llm_response
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)

            needs_graph = bool(data.get("needs_graph", False))
            output_type = data.get("output_type", "simple_list")

            return InterpretationResult(
                needs_graph=needs_graph,
                output_type=output_type,
                chart_type=data.get("chart_type") if needs_graph else None,
                reason=data.get("reason", ""),
                alternatives=data.get("alternatives", []),
                key_insight=data.get("key_insight"),
                reasoning=llm_response
            )

        except Exception as e:
            logger.error(f"[INTERPRETER] Parse error: {e}")
            # Fallback to simple list
            return InterpretationResult(
                needs_graph=False,
                output_type="simple_list",
                chart_type=None,
                reason=f"Parse error: {str(e)}",
                alternatives=["table"],
                key_insight=None,
                reasoning=llm_response
            )

    # -------------------------------------------------------------------------
    # RULE-BASED FALLBACK
    # -------------------------------------------------------------------------

    def _rule_based_fallback(
        self,
        user_query: str,
        data_results: List[Dict[str, Any]]
    ) -> InterpretationResult:
        """
        Rule-based fallback (backward compatible).

        Args:
            user_query: User query
            data_results: Results

        Returns:
            InterpretationResult from rules
        """
        # Default: list or table (no graph unless explicit)
        if len(data_results) <= 20:
            output_type = "simple_list"
            reason = "Liste gösterimi (varsayılan)"
        else:
            output_type = "table"
            reason = "Tablo gösterimi (çok satır)"

        return InterpretationResult(
            needs_graph=False,
            output_type=output_type,
            chart_type=None,
            reason=reason,
            alternatives=["table" if output_type == "simple_list" else "simple_list"],
            key_insight=None,
            reasoning="Rule-based fallback"
        )


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_report_interpreter(
    llm: BaseChatModel,
    use_llm: bool = True,
    semantic_cache: Optional[SemanticCache] = None
) -> ReportInterpreter:
    """
    Factory function to create ReportInterpreter.

    Args:
        llm: Language model
        use_llm: Use LLM interpretation
        semantic_cache: Optional semantic cache

    Returns:
        ReportInterpreter instance
    """
    return ReportInterpreter(
        llm=llm,
        use_llm=use_llm,
        semantic_cache=semantic_cache
    )
