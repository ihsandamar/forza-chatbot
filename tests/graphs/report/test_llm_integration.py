"""
Integration Tests for LLM-Driven Report Agent

Tests for end-to-end graph flows with different feature flag combinations.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any

from langchain_core.messages import HumanMessage, AIMessage


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_llm():
    """Mock LLM with all necessary methods."""
    llm = Mock()

    # Mock chat model
    chat = Mock()
    chat.ainvoke = AsyncMock(return_value=Mock(
        content='{"intent_type": "new_query", "confidence": 0.9, "requires_clarification": false, "extracted_entities": {}}'
    ))
    llm.get_chat = Mock(return_value=chat)

    # Mock embeddings (for semantic cache)
    embeddings = Mock()
    embeddings.aembed_query = AsyncMock(return_value=[0.1, 0.2, 0.3, 0.4])
    llm.get_embeddings = Mock(return_value=embeddings)

    return llm


@pytest.fixture
def mock_text2sql_graph():
    """Mock text2sql graph."""
    graph = Mock()
    graph.ainvoke = AsyncMock(return_value={
        "sql_queries": ["SELECT * FROM Sales"],
        "results": [
            {"City": "Istanbul", "Sales": 100000},
            {"City": "Ankara", "Sales": 50000}
        ],
        "parsed_intent": {"steps": []},
        "resolved_steps": [],
        "error": None
    })
    return graph


@pytest.fixture
def mock_visualization_graph():
    """Mock visualization graph."""
    graph = Mock()
    graph.ainvoke = AsyncMock(return_value={
        "summary": "Visualization complete",
        "output_type": "bar_chart",
        "needs_graph": True,
        "plotly_html_snippet": "<div>Chart</div>",
        "error": None
    })
    return graph


@pytest.fixture
def initial_state():
    """Initial state for graph invocation."""
    return {
        "messages": [HumanMessage(content="Show me sales report")],
        "active_query_context": None,
        "query_history": [],
        "pending_question": None,
        "waiting_for_user_input": False,
        "user_clarification": None,
        "text2sql_output": None,
        "visualization_output": None,
        "error": None,
        "no_records_message": None,
        "business_context": None
    }


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestLLMDrivenFlow:
    """Test full LLM-driven flow."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full graph setup with real dependencies")
    async def test_full_llm_flow(self, mock_llm, mock_text2sql_graph, mock_visualization_graph, initial_state):
        """
        Test full LLM-driven flow with all features enabled.

        This is a template test - requires actual graph building.
        """
        from src.graphs.report import build_report_graph

        # Build graph with all LLM features
        graph = build_report_graph(
            text2sql_graph=mock_text2sql_graph,
            visualization_graph=mock_visualization_graph,
            llm=mock_llm,
            enable_llm_conversation=True,
            enable_business_insights=True,
            enable_llm_interpretation=True,
            enable_natural_response=True,
            enable_semantic_cache=True,
            enable_hitl=False  # Disable for testing
        )

        # Invoke graph
        result = await graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": "test-123"}}
        )

        # Assertions
        assert result is not None
        assert "messages" in result
        assert len(result["messages"]) > 1  # Should have response

        # Check business context was populated
        if "business_context" in result:
            business_context = result["business_context"]
            assert "key_insights" in business_context
            assert "data_summary" in business_context

        # Check LLM reasoning traces
        if "_intent_reasoning" in result:
            assert isinstance(result["_intent_reasoning"], str)


class TestBackwardCompatibility:
    """Test backward compatibility with LLM features disabled."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full graph setup with real dependencies")
    async def test_all_features_disabled(self, mock_llm, mock_text2sql_graph, mock_visualization_graph, initial_state):
        """
        Test with all LLM features disabled (backward compatible mode).

        Should work exactly like old behavior.
        """
        from src.graphs.report import build_report_graph

        # Build graph with NO LLM features
        graph = build_report_graph(
            text2sql_graph=mock_text2sql_graph,
            visualization_graph=mock_visualization_graph,
            llm=mock_llm,
            enable_llm_conversation=False,
            enable_business_insights=False,
            enable_llm_interpretation=False,
            enable_natural_response=False,
            enable_semantic_cache=False,
            enable_hitl=False
        )

        # Invoke graph
        result = await graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": "test-123"}}
        )

        # Assertions
        assert result is not None
        assert "messages" in result

        # Business context should NOT be populated
        if "business_context" in result:
            assert result["business_context"] is None

        # No LLM reasoning traces
        assert "_intent_reasoning" not in result or result.get("_intent_reasoning") is None


class TestGradualFeatureEnablement:
    """Test gradual feature enablement scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full graph setup with real dependencies")
    async def test_conversation_only(self, mock_llm, mock_text2sql_graph, mock_visualization_graph, initial_state):
        """Test with only ConversationManager enabled."""
        from src.graphs.report import build_report_graph

        graph = build_report_graph(
            text2sql_graph=mock_text2sql_graph,
            visualization_graph=mock_visualization_graph,
            llm=mock_llm,
            enable_llm_conversation=True,  # ONLY this
            enable_business_insights=False,
            enable_llm_interpretation=False,
            enable_natural_response=False,
            enable_semantic_cache=False,
            enable_hitl=False
        )

        result = await graph.ainvoke(initial_state, config={"configurable": {"thread_id": "test"}})

        # Should have intent reasoning
        if "_intent_reasoning" in result:
            assert isinstance(result["_intent_reasoning"], str)

        # Should NOT have business context
        assert result.get("business_context") is None

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full graph setup with real dependencies")
    async def test_insights_only(self, mock_llm, mock_text2sql_graph, mock_visualization_graph, initial_state):
        """Test with only BusinessContextTracker enabled."""
        from src.graphs.report import build_report_graph

        graph = build_report_graph(
            text2sql_graph=mock_text2sql_graph,
            visualization_graph=mock_visualization_graph,
            llm=mock_llm,
            enable_llm_conversation=False,
            enable_business_insights=True,  # ONLY this
            enable_llm_interpretation=False,
            enable_natural_response=False,
            enable_semantic_cache=False,
            enable_hitl=False
        )

        result = await graph.ainvoke(initial_state, config={"configurable": {"thread_id": "test"}})

        # Should have business context
        if "business_context" in result:
            assert result["business_context"] is not None
            assert "key_insights" in result["business_context"]


class TestErrorHandling:
    """Test error handling and fallbacks."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full graph setup with real dependencies")
    async def test_llm_failure_fallback(self, mock_llm, mock_text2sql_graph, mock_visualization_graph, initial_state):
        """Test fallback behavior when LLM fails."""
        # Make LLM fail
        mock_llm.get_chat().ainvoke = AsyncMock(side_effect=Exception("LLM Error"))

        from src.graphs.report import build_report_graph

        graph = build_report_graph(
            text2sql_graph=mock_text2sql_graph,
            visualization_graph=mock_visualization_graph,
            llm=mock_llm,
            enable_llm_conversation=True,
            enable_business_insights=True,
            enable_llm_interpretation=True,
            enable_natural_response=True,
            enable_hitl=False
        )

        # Should not crash, should use fallbacks
        result = await graph.ainvoke(initial_state, config={"configurable": {"thread_id": "test"}})

        assert result is not None
        assert "messages" in result

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full graph setup with real dependencies")
    async def test_empty_results_handling(self, mock_llm, mock_text2sql_graph, mock_visualization_graph, initial_state):
        """Test handling of empty query results."""
        # Make text2sql return empty results
        mock_text2sql_graph.ainvoke = AsyncMock(return_value={
            "sql_queries": ["SELECT * FROM Sales WHERE 1=0"],
            "results": [],  # EMPTY
            "error": None
        })

        from src.graphs.report import build_report_graph

        graph = build_report_graph(
            text2sql_graph=mock_text2sql_graph,
            visualization_graph=mock_visualization_graph,
            llm=mock_llm,
            enable_llm_conversation=True,
            enable_business_insights=True,
            enable_llm_interpretation=True,
            enable_natural_response=True,
            enable_hitl=False
        )

        result = await graph.ainvoke(initial_state, config={"configurable": {"thread_id": "test"}})

        # Should handle gracefully
        assert result is not None
        # Should have no_records_message or appropriate response
        # (exact behavior depends on implementation)


class TestSemanticCache:
    """Test semantic cache behavior in integration."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full graph setup with real dependencies")
    async def test_cache_reduces_llm_calls(self, mock_llm, mock_text2sql_graph, mock_visualization_graph):
        """Test that semantic cache reduces LLM calls for similar queries."""
        from src.graphs.report import build_report_graph

        graph = build_report_graph(
            text2sql_graph=mock_text2sql_graph,
            visualization_graph=mock_visualization_graph,
            llm=mock_llm,
            enable_llm_conversation=True,
            enable_business_insights=True,
            enable_semantic_cache=True,  # CACHE ENABLED
            enable_hitl=False
        )

        # First query
        state1 = {
            "messages": [HumanMessage(content="Show me sales report")],
            "active_query_context": None,
            "query_history": [],
            "pending_question": None,
            "waiting_for_user_input": False,
            "text2sql_output": None,
            "visualization_output": None,
            "error": None,
            "no_records_message": None
        }

        result1 = await graph.ainvoke(state1, config={"configurable": {"thread_id": "test"}})
        call_count_1 = mock_llm.get_chat().ainvoke.call_count

        # Similar query (should hit cache)
        state2 = {
            "messages": [HumanMessage(content="Show me the sales report")],  # Similar
            "active_query_context": None,
            "query_history": [],
            "pending_question": None,
            "waiting_for_user_input": False,
            "text2sql_output": None,
            "visualization_output": None,
            "error": None,
            "no_records_message": None
        }

        result2 = await graph.ainvoke(state2, config={"configurable": {"thread_id": "test2"}})
        call_count_2 = mock_llm.get_chat().ainvoke.call_count

        # Second query should make fewer LLM calls (cache hits)
        # (Exact assertion depends on cache threshold and implementation)


# =============================================================================
# PERFORMANCE TESTS
# =============================================================================

class TestPerformance:
    """Performance and token usage tests."""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full graph setup and token counting")
    async def test_token_usage_full_mode(self, mock_llm, mock_text2sql_graph, mock_visualization_graph, initial_state):
        """Test token usage with all features enabled."""
        # Would require actual token counting integration
        pass

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full graph setup and token counting")
    async def test_token_usage_minimal_mode(self, mock_llm, mock_text2sql_graph, mock_visualization_graph, initial_state):
        """Test token usage with minimal features."""
        # Would require actual token counting integration
        pass


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
