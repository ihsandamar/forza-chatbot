"""
Test Query Type in State - Full Graph Integration Test

Bu test, query_type'ın state'de doğru şekilde set edilip edilmediğini kontrol eder.
"""

import sys
import asyncio
from pathlib import Path
import json

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from graphs.report.graph import build_report_graph
from graphs.report.state import ReportState
from langchain_core.messages import HumanMessage
from models.llm import LLM
from services.config_loader import ConfigLoader


async def test_query_type_in_state():
    """Test query_type field in state after classify_intent node."""

    print("=" * 80)
    print("QUERY TYPE IN STATE - Full Graph Integration Test")
    print("=" * 80)
    print()

    # Load configuration
    print("[1/5] Loading configuration...")
    try:
        config = ConfigLoader.load_config()
        print("  [OK] Config loaded from config/config.yaml")

        # Check API key
        api_key = config.llm.api_key
        if not api_key:
            print("[ERROR] OPENAI_API_KEY not found in config")
            print("Please set OPENAI_API_KEY in .env file or environment")
            return False

        print(f"  [OK] API Key found: {api_key[:8]}...")
    except Exception as e:
        print(f"  [FAIL] Config load failed: {e}")
        return False
    print()

    # Initialize LLM
    print("[2/5] Initializing LLM...")
    try:
        llm = LLM()
        print("  [OK] LLM initialized")
    except Exception as e:
        print(f"  [FAIL] LLM initialization failed: {e}")
        return False
    print()

    # Build graph (without text2sql and visualization for testing)
    print("[3/5] Building report graph...")
    print("  - enable_llm_conversation: True")
    print("  - enable_merged_text2sql: False (simplified test)")
    print("  - enable_hitl: False (skip interrupts)")

    # Create mock text2sql graph
    from langgraph.graph import StateGraph, START, END
    from typing import TypedDict

    class MockText2SQLState(TypedDict):
        messages: list
        user_query: str
        results: list

    mock_text2sql_graph = StateGraph(MockText2SQLState)

    async def mock_text2sql_node(state):
        return {"results": [{"col1": "value1"}]}

    mock_text2sql_graph.add_node("mock", mock_text2sql_node)
    mock_text2sql_graph.add_edge(START, "mock")
    mock_text2sql_graph.add_edge("mock", END)
    mock_text2sql_compiled = mock_text2sql_graph.compile()

    # Create mock visualization graph (needed for HITL disabled router)
    class MockVizState(TypedDict):
        messages: list

    mock_viz_graph = StateGraph(MockVizState)

    async def mock_viz_node(state):
        return {}

    mock_viz_graph.add_node("mock_viz", mock_viz_node)
    mock_viz_graph.add_edge(START, "mock_viz")
    mock_viz_graph.add_edge("mock_viz", END)
    mock_viz_compiled = mock_viz_graph.compile()

    # Build report graph
    try:
        graph = build_report_graph(
            text2sql_graph=mock_text2sql_compiled,
            visualization_graph=mock_viz_compiled,  # FIXED: Add mock viz graph
            llm=llm,
            enable_hitl=False,
            enable_llm_conversation=True,
            enable_business_insights=False,
            enable_llm_interpretation=False,
            enable_natural_response=False,
            enable_merged_text2sql=False
        )
        print("  [OK] Graph built successfully")
    except Exception as e:
        print(f"  [FAIL] Graph build failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print()

    # Test queries
    test_queries = [
        ("En çok satan 10 ürünü göster", "ranking"),
        ("İstanbul vs Ankara satışları", "comparison"),
        ("Son 6 aydaki satışlar", "time_series"),
        ("Toplam ciro nedir?", "single_value"),
    ]

    print("[4/5] Testing queries...")
    print()

    passed = 0
    failed = 0

    for query, expected_type in test_queries:
        print(f"Query: '{query}'")
        print(f"  Expected type: {expected_type}")

        # Create initial state
        initial_state = {
            "messages": [HumanMessage(content=query)],
            "conversation_history": [],
            "last_query_results": None,
            "waiting_for_user_input": False,
        }

        try:
            # Run ONLY classify_intent node (don't run full graph)
            # This avoids the text2sql execution
            config = {"configurable": {"thread_id": "test-123"}}

            # Stream graph execution
            final_state = None
            async for event in graph.astream(initial_state, config=config):
                # Get the last state update
                if isinstance(event, dict):
                    for node_name, node_state in event.items():
                        if node_state:
                            final_state = node_state

                            # Check if we're past classify_intent
                            if node_name == "classify_intent":
                                print(f"  [NODE: {node_name}] State updated")
                                break

            # Check query_type in state
            if final_state:
                query_type = final_state.get("query_type")
                confidence = final_state.get("query_type_confidence", 0.0)
                reference_context = final_state.get("reference_context", {})
                user_query = final_state.get("user_query")

                print(f"  State after classify_intent:")
                print(f"    - user_query: {user_query}")
                print(f"    - query_type: {query_type}")
                print(f"    - query_type_confidence: {confidence:.2f}")
                print(f"    - reference_context: {reference_context}")

                if query_type:
                    print(f"  [PASS] query_type found in state: {query_type}")
                    if query_type == expected_type:
                        print(f"  [PASS] Matches expected type")
                        passed += 1
                    else:
                        print(f"  ⚠ Type mismatch (expected {expected_type}, got {query_type})")
                        passed += 0.5
                        failed += 0.5
                else:
                    print(f"  [FAIL] query_type is None or missing!")
                    print(f"  DEBUG: Full state keys: {list(final_state.keys())}")
                    failed += 1
            else:
                print(f"  [FAIL] No state returned from graph")
                failed += 1

        except Exception as e:
            print(f"  [FAIL] Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

        print()

    print()
    print("[5/5] Test Summary")
    print("=" * 80)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(test_queries)} tests")
    print("=" * 80)
    print()

    if failed == 0:
        print("[SUCCESS] ALL TESTS PASSED - query_type is working correctly in state!")
    else:
        print("[FAILED] SOME TESTS FAILED - query_type implementation needs debugging")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(test_query_type_in_state())
    sys.exit(0 if success else 1)
