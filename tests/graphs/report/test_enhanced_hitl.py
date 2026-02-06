"""
Enhanced HITL System Tests

Tests for ambiguity detection, question building, and clarification processing.

Test Coverage:
- Context ambiguity detection
- Prompt scope ambiguity detection
- Intent ambiguity detection
- Column/value ambiguity detection
- Question building
- Clarification processing
- Auto-resolution
- Priority routing
"""

import pytest
from src.graphs.report.ambiguity_framework import (
    AmbiguityType,
    AmbiguityContext,
    build_context_ambiguity_metadata
)
from src.graphs.report.ambiguity_detectors import (
    IntentStageDetector,
    MetadataStageDetector
)
from src.graphs.report.hitl_question_builder import (
    HITLQuestionBuilder,
    QuestionTemplate
)
from src.graphs.report.ambiguity_router import (
    AmbiguityRouter,
    AmbiguityFallback,
    should_trigger_hitl
)


# =============================================================================
# TEST: Context Ambiguity Detection (Priority #1 - MOST CRITICAL)
# =============================================================================

class TestContextAmbiguity:
    """Test context ambiguity detection."""

    def test_context_ambiguity_detected(self):
        """
        Test Scenario 1 from plan:
        Context: Ankara + Son 3 yıl
        Query: "Hangi kategoriden satış olmuş?"
        Expected: Context ambiguity detected
        """
        # Arrange
        state = {
            "user_query": "Hangi kategoriden satış olmuş?",
            "active_query_context": {
                "applied_filters": [
                    {"column": "BranchCityName", "value": "Ankara"},
                    {"column": "DocumentDate", "value": "Son 3 yıl"}
                ],
                "grouping_columns": [],
                "result_row_count": 125
            },
            "_intent_type": "new_query",
            "_confidence": 0.7,
            "_extracted_entities": {"new_dimension": "kategori"},
            "clarification_count": 0
        }

        detector = IntentStageDetector()

        # Act
        ambiguity = detector._detect_context_ambiguity(state, state["user_query"])

        # Assert
        assert ambiguity is not None
        assert ambiguity.ambiguity_type == AmbiguityType.CONTEXT
        assert ambiguity.metadata["new_dimension"] == "kategori"
        assert len(ambiguity.metadata["applied_filters"]) == 2
        assert not ambiguity.metadata["has_context_reference"]

    def test_no_context_ambiguity_with_reference(self):
        """
        Test Scenario 2 from plan:
        Context: Ankara + Son 3 yıl
        Query: "Burdaki kategorilere göre göster"
        Expected: NO context ambiguity (has reference)
        """
        # Arrange
        state = {
            "user_query": "Burdaki kategorilere göre göster",
            "active_query_context": {
                "applied_filters": [
                    {"column": "BranchCityName", "value": "Ankara"}
                ],
                "grouping_columns": [],
                "result_row_count": 125
            },
            "_intent_type": "modify_aggregation",
            "_confidence": 0.9,
            "clarification_count": 0
        }

        detector = IntentStageDetector()

        # Act
        ambiguity = detector._detect_context_ambiguity(state, state["user_query"])

        # Assert
        assert ambiguity is None  # No ambiguity because query has "burdaki"

    def test_no_context_ambiguity_without_filters(self):
        """
        Test: No context ambiguity when no filters applied.
        """
        # Arrange
        state = {
            "user_query": "Hangi kategoriden satış olmuş?",
            "active_query_context": {
                "applied_filters": [],  # No filters
                "grouping_columns": [],
                "result_row_count": 0
            },
            "_intent_type": "new_query",
            "clarification_count": 0
        }

        detector = IntentStageDetector()

        # Act
        ambiguity = detector._detect_context_ambiguity(state, state["user_query"])

        # Assert
        assert ambiguity is None  # No ambiguity because no filters


# =============================================================================
# TEST: Prompt Scope Ambiguity Detection (Priority #2)
# =============================================================================

class TestPromptScopeAmbiguity:
    """Test prompt scope ambiguity detection."""

    @pytest.mark.asyncio
    async def test_short_query_detected(self):
        """
        Test Scenario 2 from plan:
        Query: "Satışlar" (1 word)
        Expected: Prompt scope ambiguity detected
        """
        # Arrange
        state = {
            "user_query": "Satışlar",
            "active_query_context": None,  # No context
            "clarification_count": 0
        }

        detector = IntentStageDetector()

        # Act
        ambiguity = await detector._detect_prompt_scope(state, state["user_query"])

        # Assert
        assert ambiguity is not None
        assert ambiguity.ambiguity_type == AmbiguityType.PROMPT_SCOPE
        assert ambiguity.metadata["word_count"] == 1
        assert len(ambiguity.candidates) > 0  # Has suggestions

    @pytest.mark.asyncio
    async def test_no_prompt_scope_for_long_query(self):
        """
        Test: No prompt scope ambiguity for queries > 3 words.
        """
        # Arrange
        state = {
            "user_query": "Son 3 yılda Ankara'daki satışları göster",  # 6 words
            "active_query_context": None,
            "clarification_count": 0
        }

        detector = IntentStageDetector()

        # Act
        ambiguity = await detector._detect_prompt_scope(state, state["user_query"])

        # Assert
        assert ambiguity is None  # Not short enough


# =============================================================================
# TEST: Question Building
# =============================================================================

class TestQuestionBuilding:
    """Test HITL question generation."""

    def test_build_context_question(self):
        """
        Test context ambiguity question formatting.
        """
        # Arrange
        ambiguity_ctx = AmbiguityContext(
            ambiguity_type=AmbiguityType.CONTEXT,
            user_query="Hangi kategoriden satış olmuş?",
            active_context_summary="Ankara | Son 3 yıl | 125 satır",
            candidates=["keep_filters", "clear_filters"],
            metadata=build_context_ambiguity_metadata(
                {"active_query_context": {
                    "applied_filters": [
                        {"column": "BranchCityName", "value": "Ankara"},
                        {"column": "DocumentDate", "value": "Son 3 yıl"}
                    ],
                    "result_row_count": 125
                }},
                new_dimension="kategori"
            ),
            detection_stage="intent"
        )

        builder = HITLQuestionBuilder()

        # Act
        question = builder.build_question(ambiguity_ctx)

        # Assert
        assert isinstance(question, QuestionTemplate)
        assert "filtreleri koruyarak" in question.title.lower()
        assert len(question.options) == 2
        assert "Evet" in question.options[0] or "kategori" in question.options[0].lower()
        assert "Hayır" in question.options[1] or "TÜM" in question.options[1]

    def test_build_prompt_scope_question(self):
        """
        Test prompt scope ambiguity question formatting.
        """
        # Arrange
        ambiguity_ctx = AmbiguityContext(
            ambiguity_type=AmbiguityType.PROMPT_SCOPE,
            user_query="Satışlar",
            candidates=["list_all", "summary", "filtered", "grouped"],
            metadata={
                "query": "Satışlar",
                "word_count": 1,
                "suggested_clarifications": [
                    "Tüm satış kayıtlarını listele",
                    "Satış özet istatistikleri göster",
                    "Belirli kritere göre satışları filtrele",
                    "Gruplama ile satış analizi yap"
                ]
            },
            detection_stage="prompt"
        )

        builder = HITLQuestionBuilder()

        # Act
        question = builder.build_question(ambiguity_ctx)

        # Assert
        assert isinstance(question, QuestionTemplate)
        assert "kısa" in question.title.lower()
        assert len(question.options) == 4


# =============================================================================
# TEST: Ambiguity Routing
# =============================================================================

class TestAmbiguityRouting:
    """Test priority-based ambiguity selection."""

    def test_priority_selection(self):
        """
        Test: Multiple ambiguities, highest priority selected.
        Context + Value → Context selected (higher priority)
        """
        # Arrange
        context_ambiguity = AmbiguityContext(
            ambiguity_type=AmbiguityType.CONTEXT,
            user_query="test",
            candidates=[]
        )

        value_ambiguity = AmbiguityContext(
            ambiguity_type=AmbiguityType.VALUE,
            user_query="test",
            candidates=[]
        )

        ambiguities = [value_ambiguity, context_ambiguity]  # Reverse order

        # Act
        selected = AmbiguityRouter.select_ambiguity(ambiguities)

        # Assert
        assert selected == context_ambiguity  # Higher priority

    def test_auto_resolve_value_ambiguity(self):
        """
        Test: Auto-resolve value ambiguity with high confidence.
        """
        # Arrange
        ambiguity_ctx = AmbiguityContext(
            ambiguity_type=AmbiguityType.VALUE,
            user_query="test",
            candidates=["İstanbul", "İstanbul Mağazası"],
            confidence_scores={
                "İstanbul": 0.95,
                "İstanbul Mağazası": 0.3
            }
        )

        # Act
        resolved = AmbiguityFallback.auto_resolve_value_ambiguity(ambiguity_ctx)

        # Assert
        assert resolved == "İstanbul"  # Highest confidence

    def test_should_trigger_hitl_with_max_count(self):
        """
        Test: HITL not triggered when max clarification count reached.
        """
        # Arrange
        state = {"clarification_count": 3}
        ambiguity = AmbiguityContext(
            ambiguity_type=AmbiguityType.CONTEXT,
            user_query="test",
            candidates=[]
        )

        # Act
        should_trigger = should_trigger_hitl(state, ambiguity, max_clarifications=3)

        # Assert
        assert not should_trigger  # Max reached


# =============================================================================
# TEST: Clarification Processing
# =============================================================================

class TestClarificationProcessing:
    """Test clarification response processing."""

    def test_process_context_clarification_keep_filters(self):
        """
        Test: User chose to keep filters.
        Expected: execution_mode=delta, intent=modify_filter
        """
        # Arrange
        from src.graphs.report.nodes import _process_context_clarification

        state = {
            "user_query": "Hangi kategoriden satış olmuş?",
            "active_query_context": {"applied_filters": [{"column": "BranchCityName", "value": "Ankara"}]}
        }

        ambiguity_ctx = AmbiguityContext(
            ambiguity_type=AmbiguityType.CONTEXT,
            user_query=state["user_query"],
            candidates=[]
        )

        user_response = "1"  # Option 1: Keep filters

        # Act
        result = _process_context_clarification(state, ambiguity_ctx, user_response)

        # Assert
        assert result["_execution_mode"] == "delta"
        assert result["_intent_type"] == "modify_filter"
        assert "active_query_context" not in result  # Context preserved

    def test_process_context_clarification_clear_filters(self):
        """
        Test: User chose to clear filters.
        Expected: execution_mode=full, intent=new_query, context cleared
        """
        # Arrange
        from src.graphs.report.nodes import _process_context_clarification

        state = {
            "user_query": "Hangi kategoriden satış olmuş?",
            "active_query_context": {"applied_filters": [{"column": "BranchCityName", "value": "Ankara"}]}
        }

        ambiguity_ctx = AmbiguityContext(
            ambiguity_type=AmbiguityType.CONTEXT,
            user_query=state["user_query"],
            candidates=[]
        )

        user_response = "2"  # Option 2: Clear filters

        # Act
        result = _process_context_clarification(state, ambiguity_ctx, user_response)

        # Assert
        assert result["_execution_mode"] == "full"
        assert result["_intent_type"] == "new_query"
        assert result["active_query_context"] is None  # Context cleared


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
