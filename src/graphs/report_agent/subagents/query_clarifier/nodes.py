import logging
import re
from typing import Optional

from langgraph.types import interrupt

from .prompts import (
    CLARITY_ANALYZER_PROMPT,
    VAGUE_CLARITY_PROMPT,
    ClarityAnalysisResult,
)

logger = logging.getLogger(__name__)


def _extract_sql_summary(sql: str) -> str:
    """WHERE ve GROUP BY kısımlarını çıkararak MODIFY_QUERY bağlamı oluşturur."""
    parts = []

    where_match = re.search(
        r"\bWHERE\b(.+?)(?:\bGROUP BY\b|\bORDER BY\b|\bLIMIT\b|$)",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if where_match:
        parts.append(f"WHERE: {where_match.group(1).strip()[:200]}")

    groupby_match = re.search(
        r"\bGROUP BY\b(.+?)(?:\bORDER BY\b|\bLIMIT\b|$)",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    if groupby_match:
        parts.append(f"GROUP BY: {groupby_match.group(1).strip()[:100]}")

    return "; ".join(parts) if parts else "—"


def _is_accepted(answer: str) -> bool:
    return answer.lower().strip() in ("evet", "evet, devam et", "e", "yes", "y", "1", "ok", "tamam")


def create_clarity_analyzer_node(
    llm, clarity_threshold: float = 0.65, enable_clarifier: bool = True
):
    """Factory: returns async clarity_analyzer_node with dependencies baked in."""

    structured_llm = llm.with_structured_output(ClarityAnalysisResult)

    async def clarity_analyzer_node(state: dict) -> dict:
        if not enable_clarifier:
            return {"clarifier_decision": "PASS"}

        user_query: str = state.get("user_query", "")
        intent_type: str = state.get("intent_type", "NEW_QUERY")
        active_sql: Optional[str] = state.get("active_sql")

        logger.info(f"[CLARITY_ANALYZER] intent={intent_type} query={user_query[:80]!r}")

        if intent_type == "VAGUE_QUERY":
            prompt = VAGUE_CLARITY_PROMPT.format(user_query=user_query)
        else:
            active_sql_summary = (
                _extract_sql_summary(active_sql)
                if active_sql and intent_type == "MODIFY_QUERY"
                else "—"
            )
            prompt = CLARITY_ANALYZER_PROMPT.format(
                intent_type=intent_type,
                has_active_sql="Evet" if active_sql else "Hayır",
                active_sql_summary=active_sql_summary,
                user_query=user_query,
            )

        try:
            result: ClarityAnalysisResult = await structured_llm.ainvoke(prompt)
        except Exception as exc:
            logger.warning(f"[CLARITY_ANALYZER] LLM failed ({exc!r}), returning PASS")
            return {"clarifier_decision": "PASS"}

        logger.info(
            f"[CLARITY_ANALYZER] score={result.clarity_score:.2f} can_suggest={result.can_suggest}"
        )

        needs_clarification = result.can_suggest and result.suggested_query is not None and (
            intent_type == "VAGUE_QUERY" or result.clarity_score < clarity_threshold
        )

        if not needs_clarification:
            logger.info("[CLARITY_ANALYZER] Score sufficient or no suggestion — PASS")
            return {"clarifier_decision": "PASS"}

        answer = interrupt(
            {
                "type": "clarification",
                "question": result.suggestion_message,
                "suggested_query": result.suggested_query,
                "options": ["Evet, devam et", "Hayır, orijinal sorguyu kullan"],
            }
        )

        if _is_accepted(str(answer)):
            logger.info(f"[CLARITY_ANALYZER] User accepted → CLARIFIED: {result.suggested_query!r}")
            return {
                "user_query": result.suggested_query,
                "suggested_query": result.suggested_query,
                "clarifier_decision": "CLARIFIED",
            }
        else:
            logger.info("[CLARITY_ANALYZER] User rejected → PASS")
            return {"clarifier_decision": "PASS"}

    return clarity_analyzer_node
