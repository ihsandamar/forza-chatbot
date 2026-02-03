"""
Smart Context Window Manager

Intelligent message selection for LLM context, replacing blind "last N messages" truncation.

Features:
- Keyword overlap detection
- Recency weighting
- Entity-based relevance scoring
- Token budget management
- Preserves conversation coherence

Usage:
    window = ContextWindow(max_tokens=2000)
    relevant_messages = window.get_relevant_context(
        current_query="Show me Istanbul sales",
        full_history=messages,
        active_context=context
    )
"""

import logging
import re
from typing import List, Dict, Any, Optional, Set
from collections import Counter
from datetime import datetime

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

logger = logging.getLogger(__name__)


# =============================================================================
# CONTEXT WINDOW MANAGER
# =============================================================================

class ContextWindow:
    """
    Smart context window with relevance-based message selection.

    Replaces blind "last N messages" with intelligent selection based on:
    - Keyword overlap with current query
    - Recency (newer = more relevant)
    - Entity mentions (tables, columns, filters)
    - Conversation turns (keep Q&A pairs together)
    """

    def __init__(
        self,
        max_tokens: int = 2000,
        min_messages: int = 3,
        max_messages: int = 10,
        recency_weight: float = 0.3,
        keyword_weight: float = 0.4,
        entity_weight: float = 0.3
    ):
        """
        Initialize context window manager.

        Args:
            max_tokens: Maximum token budget for context
            min_messages: Minimum messages to keep (recent)
            max_messages: Maximum messages to include
            recency_weight: Weight for recency score (0.0-1.0)
            keyword_weight: Weight for keyword overlap (0.0-1.0)
            entity_weight: Weight for entity overlap (0.0-1.0)
        """
        self.max_tokens = max_tokens
        self.min_messages = min_messages
        self.max_messages = max_messages
        self.recency_weight = recency_weight
        self.keyword_weight = keyword_weight
        self.entity_weight = entity_weight

        logger.info(f"[CONTEXT] Initialized context window (max_tokens={max_tokens})")

    def get_relevant_context(
        self,
        current_query: str,
        full_history: List[BaseMessage],
        active_context: Optional[Dict[str, Any]] = None
    ) -> List[BaseMessage]:
        """
        Get relevant messages for current query.

        Args:
            current_query: Current user query
            full_history: Full conversation history
            active_context: Active query context (for entity extraction)

        Returns:
            List of relevant messages within token budget
        """
        if not full_history:
            return []

        # Always keep last min_messages (recent context)
        min_keep = full_history[-self.min_messages:] if len(full_history) >= self.min_messages else full_history

        # If full history is small, return all
        if len(full_history) <= self.min_messages:
            return full_history

        # Extract keywords and entities from current query
        query_keywords = self._extract_keywords(current_query)
        query_entities = self._extract_entities(current_query, active_context)

        # Score all messages
        scored_messages = []
        for i, msg in enumerate(full_history):
            # Skip already included min_messages
            if msg in min_keep:
                continue

            score = self._score_message(
                message=msg,
                index=i,
                total_count=len(full_history),
                query_keywords=query_keywords,
                query_entities=query_entities
            )

            scored_messages.append((score, i, msg))

        # Sort by score (descending)
        scored_messages.sort(reverse=True, key=lambda x: x[0])

        # Select messages within token budget
        selected = list(min_keep)  # Start with min_messages
        current_tokens = self._estimate_tokens(selected)

        for score, idx, msg in scored_messages:
            if len(selected) >= self.max_messages:
                break

            msg_tokens = self._estimate_tokens([msg])

            if current_tokens + msg_tokens <= self.max_tokens:
                selected.append(msg)
                current_tokens += msg_tokens

        # Sort by original order (maintain conversation flow)
        selected_indices = {id(msg): full_history.index(msg) for msg in selected}
        selected.sort(key=lambda msg: selected_indices[id(msg)])

        logger.info(f"[CONTEXT] Selected {len(selected)}/{len(full_history)} messages (~{current_tokens} tokens)")

        return selected

    # -------------------------------------------------------------------------
    # SCORING
    # -------------------------------------------------------------------------

    def _score_message(
        self,
        message: BaseMessage,
        index: int,
        total_count: int,
        query_keywords: Set[str],
        query_entities: Set[str]
    ) -> float:
        """
        Score message relevance.

        Args:
            message: Message to score
            index: Message index in history
            total_count: Total message count
            query_keywords: Keywords from current query
            query_entities: Entities from current query

        Returns:
            Relevance score (0.0-1.0)
        """
        # Recency score (newer = higher)
        recency_score = index / max(total_count - 1, 1)

        # Keyword overlap score
        msg_keywords = self._extract_keywords(message.content)
        keyword_overlap = len(query_keywords & msg_keywords)
        keyword_score = min(keyword_overlap / max(len(query_keywords), 1), 1.0)

        # Entity overlap score
        msg_entities = self._extract_entities(message.content, None)
        entity_overlap = len(query_entities & msg_entities)
        entity_score = min(entity_overlap / max(len(query_entities), 1), 1.0)

        # Weighted sum
        total_score = (
            self.recency_weight * recency_score +
            self.keyword_weight * keyword_score +
            self.entity_weight * entity_score
        )

        return total_score

    # -------------------------------------------------------------------------
    # KEYWORD & ENTITY EXTRACTION
    # -------------------------------------------------------------------------

    def _extract_keywords(self, text: str) -> Set[str]:
        """
        Extract keywords from text.

        Args:
            text: Text to extract from

        Returns:
            Set of keywords (lowercase, no stopwords)
        """
        if not text:
            return set()

        # Lowercase
        text = text.lower()

        # Remove punctuation
        text = re.sub(r'[^\w\s]', ' ', text)

        # Split into words
        words = text.split()

        # Remove stopwords (Turkish + English common words)
        stopwords = {
            'bir', 'bu', 've', 'de', 'da', 'ile', 'için', 'mi', 'mu', 'mü',
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had',
            'do', 'does', 'did', 'will', 'would', 'could', 'should',
            'göster', 'ver', 'yap', 'et', 'ol', 'getir'
        }

        # Filter
        keywords = {w for w in words if len(w) > 2 and w not in stopwords}

        return keywords

    def _extract_entities(
        self,
        text: str,
        active_context: Optional[Dict[str, Any]]
    ) -> Set[str]:
        """
        Extract entities (tables, columns, values) from text.

        Args:
            text: Text to extract from
            active_context: Active query context with table/column info

        Returns:
            Set of entity strings
        """
        entities = set()

        # Common table names (Turkish)
        table_patterns = [
            r'satış', r'müşteri', r'ürün', r'kategori',
            r'sales', r'customer', r'product', r'category'
        ]

        # Common column names
        column_patterns = [
            r'tarih', r'date', r'tutar', r'amount', r'miktar', r'quantity',
            r'şehir', r'city', r'kategori', r'category', r'ad', r'name'
        ]

        text_lower = text.lower()

        # Extract matches
        for pattern in table_patterns + column_patterns:
            matches = re.findall(pattern, text_lower)
            entities.update(matches)

        # Add entities from active context
        if active_context:
            # Table name
            table = active_context.get('current_table', '')
            if table:
                entities.add(table.lower())

            # Columns
            grouping = active_context.get('grouping_columns', [])
            entities.update([c.lower() for c in grouping])

            # Filter columns
            filters = active_context.get('applied_filters', [])
            for f in filters:
                col = f.get('column', '')
                if col:
                    entities.add(col.lower())

        return entities

    # -------------------------------------------------------------------------
    # TOKEN ESTIMATION
    # -------------------------------------------------------------------------

    def _estimate_tokens(self, messages: List[BaseMessage]) -> int:
        """
        Estimate token count for messages.

        Uses simple heuristic: ~1.3 tokens per word for Turkish/English mix.

        Args:
            messages: Messages to estimate

        Returns:
            Estimated token count
        """
        total_chars = sum(len(msg.content) for msg in messages)

        # Rough estimate: 4 chars per token on average for Turkish
        # (Turkish is slightly more compact than English)
        estimated_tokens = total_chars // 4

        return estimated_tokens


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_recent_context(
    messages: List[BaseMessage],
    n: int = 5
) -> List[BaseMessage]:
    """
    Simple fallback: Get last N messages.

    Use when ContextWindow is not available or disabled.

    Args:
        messages: Full message history
        n: Number of recent messages to keep

    Returns:
        Last N messages
    """
    return messages[-n:] if len(messages) > n else messages


def format_context_for_llm(
    messages: List[BaseMessage],
    active_context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Format context messages for LLM prompt.

    Args:
        messages: Context messages
        active_context: Active query context

    Returns:
        Formatted context string
    """
    parts = []

    # Add active context summary
    if active_context:
        table = active_context.get('current_table', '')
        if table:
            parts.append(f"Aktif Tablo: {table}")

        filters = active_context.get('applied_filters', [])
        if filters:
            filter_strs = [f"{f['column']}={f['value']}" for f in filters]
            parts.append(f"Filtreler: {', '.join(filter_strs)}")

    # Add recent messages
    if messages:
        parts.append("\nSon Mesajlar:")
        for msg in messages[-5:]:  # Last 5 for summary
            role = "Kullanıcı" if isinstance(msg, HumanMessage) else "Asistan"
            content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
            parts.append(f"- {role}: {content}")

    return "\n".join(parts) if parts else "Yeni conversation"
