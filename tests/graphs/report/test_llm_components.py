"""
Unit Tests for LLM-Driven Report Agent Components

Tests for new LLM-powered components:
- SemanticCache
- ContextWindow
- ConversationManager
- BusinessContextTracker
- ReportInterpreter
- ResponseGenerator
"""

import pytest
import asyncio
from typing import List, Dict, Any
from unittest.mock import Mock, AsyncMock, patch

# Mock LangChain components to avoid dependencies
from langchain_core.messages import HumanMessage, AIMessage


# =============================================================================
# SEMANTIC CACHE TESTS
# =============================================================================

class TestSemanticCache:
    """Tests for SemanticCache component."""

    @pytest.fixture
    def mock_embeddings(self):
        """Mock embeddings model."""
        embeddings = Mock()
        embeddings.aembed_query = AsyncMock(return_value=[0.1, 0.2, 0.3, 0.4])
        return embeddings

    @pytest.fixture
    def semantic_cache(self, mock_embeddings):
        """Create SemanticCache instance."""
        from src.graphs.report.semantic_cache import SemanticCache
        return SemanticCache(
            embeddings=mock_embeddings,
            threshold=0.95,
            ttl=3600
        )

    @pytest.mark.asyncio
    async def test_cache_miss_and_compute(self, semantic_cache):
        """Test cache miss triggers computation."""
        compute_called = False

        async def compute_fn():
            nonlocal compute_called
            compute_called = True
            return "computed_result"

        result = await semantic_cache.get_or_compute(
            query="test query",
            compute_fn=compute_fn
        )

        assert result == "computed_result"
        assert compute_called
        assert semantic_cache._misses == 1

    @pytest.mark.asyncio
    async def test_cache_hit_exact_match(self, semantic_cache):
        """Test exact cache hit doesn't recompute."""
        # First call - cache miss
        result1 = await semantic_cache.get_or_compute(
            query="test query",
            compute_fn=lambda: asyncio.coroutine(lambda: "result1")()
        )

        # Second call - cache hit
        compute_called = False

        async def compute_fn():
            nonlocal compute_called
            compute_called = True
            return "result2"

        result2 = await semantic_cache.get_or_compute(
            query="test query",
            compute_fn=compute_fn
        )

        assert result2 == "result1"  # Returns cached result
        assert not compute_called
        assert semantic_cache._hits == 1

    def test_cache_stats(self, semantic_cache):
        """Test cache statistics."""
        stats = semantic_cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["total_requests"] == 0
        assert stats["hit_rate"] == 0.0

    def test_cache_invalidation(self, semantic_cache):
        """Test cache invalidation."""
        semantic_cache._cache["key1"] = Mock()
        semantic_cache._cache["key2"] = Mock()

        semantic_cache.invalidate()

        assert len(semantic_cache._cache) == 0


# =============================================================================
# CONTEXT WINDOW TESTS
# =============================================================================

class TestContextWindow:
    """Tests for ContextWindow component."""

    @pytest.fixture
    def context_window(self):
        """Create ContextWindow instance."""
        from src.graphs.report.context_window import ContextWindow
        return ContextWindow(max_tokens=2000, min_messages=3)

    @pytest.fixture
    def sample_messages(self):
        """Sample conversation messages."""
        return [
            HumanMessage(content="Show me sales report"),
            AIMessage(content="Here is the sales report"),
            HumanMessage(content="Filter by Istanbul"),
            AIMessage(content="Filtered by Istanbul"),
            HumanMessage(content="Show me details for Istanbul")
        ]

    def test_get_relevant_context_small_history(self, context_window, sample_messages):
        """Test with small history returns all messages."""
        result = context_window.get_relevant_context(
            current_query="Show more details",
            full_history=sample_messages[:3],
            active_context=None
        )

        assert len(result) == 3
        assert result == sample_messages[:3]

    def test_get_relevant_context_keyword_overlap(self, context_window):
        """Test keyword overlap increases relevance."""
        messages = [
            HumanMessage(content="Show me sales data"),  # "sales"
            AIMessage(content="Okay"),
            HumanMessage(content="Show products"),       # No "sales"
            AIMessage(content="Here are products"),
            HumanMessage(content="What about Istanbul?")  # No "sales"
        ]

        result = context_window.get_relevant_context(
            current_query="Show me sales report",  # "sales"
            full_history=messages,
            active_context=None
        )

        # Should include message with "sales" keyword
        assert any("sales" in msg.content.lower() for msg in result)

    def test_extract_keywords(self, context_window):
        """Test keyword extraction."""
        keywords = context_window._extract_keywords("Show me sales data for Istanbul")

        assert "sales" in keywords
        assert "data" in keywords
        assert "istanbul" in keywords
        assert "show" not in keywords  # Stopword
        assert "me" not in keywords    # Stopword

    def test_extract_entities_with_context(self, context_window):
        """Test entity extraction with active context."""
        active_context = {
            "current_table": "SalesData",
            "grouping_columns": ["City", "Category"],
            "applied_filters": [{"column": "Region", "value": "EMEA"}]
        }

        entities = context_window._extract_entities(
            text="Show me the sales data",
            active_context=active_context
        )

        assert "salesdata" in entities
        assert "city" in entities
        assert "region" in entities


# =============================================================================
# CONVERSATION MANAGER TESTS
# =============================================================================

class TestConversationManager:
    """Tests for ConversationManager component."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM."""
        llm = Mock()
        llm.ainvoke = AsyncMock(return_value=Mock(content='{"intent_type": "new_query", "confidence": 0.9, "requires_clarification": false, "extracted_entities": {}}'))
        return llm

    @pytest.fixture
    def conversation_manager(self, mock_llm):
        """Create ConversationManager instance."""
        from src.graphs.report.conversation_manager import ConversationManager
        return ConversationManager(
            llm=mock_llm,
            enable_llm_reasoning=True
        )

    @pytest.mark.asyncio
    async def test_understand_intent_new_query(self, conversation_manager):
        """Test intent understanding for new query."""
        intent = await conversation_manager.understand_intent(
            user_message="Show me sales report",
            active_context=None,
            conversation_history=[],
            business_context=None
        )

        assert intent.intent_type.value == "new_query"
        assert intent.confidence > 0.0

    @pytest.mark.asyncio
    async def test_generate_clarification(self, conversation_manager, mock_llm):
        """Test clarification generation."""
        mock_llm.ainvoke = AsyncMock(return_value=Mock(content='{"question": "Which table?", "options": ["Sales", "Products"], "context": "Multiple tables found"}'))

        clarification = await conversation_manager.generate_clarification(
            user_message="Show me data",
            ambiguity_type="table",
            options=["Sales", "Products"]
        )

        assert "question" in clarification
        assert "options" in clarification


# =============================================================================
# BUSINESS CONTEXT TRACKER TESTS
# =============================================================================

class TestBusinessContextTracker:
    """Tests for BusinessContextTracker component."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM."""
        llm = Mock()
        llm.ainvoke = AsyncMock(return_value=Mock(content='{"key_insights": ["Insight 1", "Insight 2"], "data_summary": "Summary", "suggested_follow_ups": ["Question 1"], "user_goal": "Goal"}'))
        return llm

    @pytest.fixture
    def business_tracker(self, mock_llm):
        """Create BusinessContextTracker instance."""
        from src.graphs.report.business_context_tracker import BusinessContextTracker
        return BusinessContextTracker(llm=mock_llm)

    @pytest.mark.asyncio
    async def test_extract_insights(self, business_tracker):
        """Test business insights extraction."""
        results = [
            {"City": "Istanbul", "Sales": 100000},
            {"City": "Ankara", "Sales": 50000}
        ]

        context = await business_tracker.extract_insights(
            user_query="Show me sales by city",
            data_results=results,
            active_context=None
        )

        assert "key_insights" in context
        assert "data_summary" in context
        assert "suggested_follow_ups" in context

    @pytest.mark.asyncio
    async def test_extract_insights_empty_results(self, business_tracker):
        """Test with empty results."""
        context = await business_tracker.extract_insights(
            user_query="Show me sales",
            data_results=[],
            active_context=None
        )

        assert context["key_insights"] == ["Sonuç bulunamadı"]
        assert "boş" in context["data_summary"].lower()


# =============================================================================
# REPORT INTERPRETER TESTS
# =============================================================================

class TestReportInterpreter:
    """Tests for ReportInterpreter component."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM."""
        llm = Mock()
        llm.ainvoke = AsyncMock(return_value=Mock(content='{"needs_graph": true, "output_type": "bar_chart", "chart_type": "bar_chart", "reason": "Best for comparison", "alternatives": ["table"], "key_insight": "Insight"}'))
        return llm

    @pytest.fixture
    def report_interpreter(self, mock_llm):
        """Create ReportInterpreter instance."""
        from src.graphs.report.report_interpreter import ReportInterpreter
        return ReportInterpreter(llm=mock_llm, use_llm=True)

    @pytest.mark.asyncio
    async def test_interpret_single_value(self, report_interpreter):
        """Test single value detection."""
        results = [{"count": 42}]

        interpretation = await report_interpreter.interpret_results(
            user_query="How many sales?",
            data_results=results
        )

        assert not interpretation.needs_graph
        assert interpretation.output_type == "single_value"

    @pytest.mark.asyncio
    async def test_interpret_explicit_chart_request(self, report_interpreter):
        """Test explicit chart request."""
        results = [{"City": "Istanbul", "Sales": 100}] * 5

        interpretation = await report_interpreter.interpret_results(
            user_query="Show me bar chart of sales",
            data_results=results
        )

        assert interpretation.needs_graph
        assert "bar" in interpretation.output_type.lower()

    @pytest.mark.asyncio
    async def test_interpret_empty_results(self, report_interpreter):
        """Test empty results."""
        interpretation = await report_interpreter.interpret_results(
            user_query="Show me data",
            data_results=[]
        )

        assert not interpretation.needs_graph
        assert interpretation.reason == "Sonuç yok"


# =============================================================================
# RESPONSE GENERATOR TESTS
# =============================================================================

class TestResponseGenerator:
    """Tests for ResponseGenerator component."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM."""
        llm = Mock()
        llm.ainvoke = AsyncMock(return_value=Mock(content="Natural language response with insights"))
        return llm

    @pytest.fixture
    def response_generator(self, mock_llm):
        """Create ResponseGenerator instance."""
        from src.graphs.report.response_generator import ResponseGenerator
        return ResponseGenerator(llm=mock_llm, use_llm=True)

    @pytest.mark.asyncio
    async def test_generate_response_with_results(self, response_generator):
        """Test response generation with results."""
        results = [{"City": "Istanbul", "Sales": 100000}]

        response = await response_generator.generate_response(
            user_query="Show me sales",
            data_results=results,
            business_context=None,
            visualization_info=None
        )

        assert isinstance(response, str)
        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_generate_response_error(self, response_generator):
        """Test error response."""
        response = await response_generator.generate_response(
            user_query="Show me sales",
            data_results=None,
            error="Database error"
        )

        assert "❌" in response
        assert "Hata" in response

    @pytest.mark.asyncio
    async def test_generate_response_no_records(self, response_generator):
        """Test no records response."""
        response = await response_generator.generate_response(
            user_query="Show me sales",
            data_results=None,
            no_records_message="No records found"
        )

        assert "ℹ️" in response
        assert "Bulunamadı" in response


# =============================================================================
# RUN TESTS
# =============================================================================

def test_sql_modification_result_has_modification_hints():
    """SqlModificationResult şeması modification_hints alanını içermeli."""
    from src.graphs.report_agent.prompts import SqlModificationResult, ModificationHint

    result = SqlModificationResult(
        modified_sql="SELECT * FROM T WHERE [CategoryName] = 'DURUMLER'",
        explanation="Kategori filtresi eklendi",
        modification_hints=[
            ModificationHint(column="CategoryName", embedded_value="dürümler")
        ],
    )
    assert len(result.modification_hints) == 1
    assert result.modification_hints[0].column == "CategoryName"
    assert result.modification_hints[0].embedded_value == "dürümler"


def test_sql_modification_result_hints_default_empty():
    """modification_hints default boş liste olmalı (geriye dönük uyumluluk)."""
    from src.graphs.report_agent.prompts import SqlModificationResult

    result = SqlModificationResult(
        modified_sql="SELECT * FROM T",
        explanation="test",
    )
    assert result.modification_hints == []


def test_modify_sql_node_returns_modification_hints():
    """modify_sql_node modification_hints döndürmeli."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from src.graphs.report_agent.prompts import SqlModificationResult, ModificationHint

    mock_result = SqlModificationResult(
        modified_sql="SELECT * FROM T WHERE [CategoryName] = 'dürümler'",
        explanation="test",
        modification_hints=[ModificationHint(column="CategoryName", embedded_value="dürümler")],
    )
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=mock_result)

    from src.graphs.report_agent.nodes import create_modify_sql_node
    node = create_modify_sql_node(mock_llm, column_metadata={})

    state = {
        "active_sql": "SELECT * FROM T",
        "active_filters": [],
        "user_query": "dürümler kategorisini göster",
    }
    result = asyncio.get_event_loop().run_until_complete(node(state))

    assert "modification_hints" in result
    assert len(result["modification_hints"]) == 1
    assert result["modification_hints"][0]["column"] == "CategoryName"
    assert result["modification_hints"][0]["embedded_value"] == "dürümler"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
