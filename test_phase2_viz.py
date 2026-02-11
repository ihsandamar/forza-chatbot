"""
Phase 2 Visualization Decision Enhancement - Test Script

Test query_type driven visualization decisions.
"""

import asyncio
from src.graphs.report.state import ReportState
from src.graphs.report.nodes import decide_visualization_node
from langchain_core.messages import HumanMessage


async def test_phase2_visualization():
    """Test Phase 2 visualization decision enhancement."""

    print("=" * 80)
    print("PHASE 2 TEST: Query Type Driven Visualization")
    print("=" * 80)

    # Test cases
    test_cases = [
        {
            "name": "Ranking Query",
            "query_type": "ranking",
            "user_query": "En çok satan 10 ürünü göster",
            "results": [
                {"product": "Ürün A", "sales": 1000},
                {"product": "Ürün B", "sales": 800},
                {"product": "Ürün C", "sales": 600},
            ],
            "expected_chart": "bar_chart",
            "expected_needs_graph": True
        },
        {
            "name": "Time Series Query",
            "query_type": "time_series",
            "user_query": "Son 6 aydaki satışlar",
            "results": [
                {"month": "2024-01", "sales": 1000},
                {"month": "2024-02", "sales": 1200},
                {"month": "2024-03", "sales": 1100},
            ],
            "expected_chart": "line_chart",
            "expected_needs_graph": True
        },
        {
            "name": "Single Value Query",
            "query_type": "single_value",
            "user_query": "Toplam ciro nedir?",
            "results": [
                {"total_revenue": 150000}
            ],
            "expected_chart": "single_value",
            "expected_needs_graph": False
        },
        {
            "name": "Comparison Query",
            "query_type": "comparison",
            "user_query": "İstanbul vs Ankara satışları",
            "results": [
                {"city": "İstanbul", "sales": 5000},
                {"city": "Ankara", "sales": 3000},
            ],
            "expected_chart": "bar_chart",
            "expected_needs_graph": True
        },
        {
            "name": "Distribution Query",
            "query_type": "distribution",
            "user_query": "Satışların şubelere göre dağılımı",
            "results": [
                {"branch": "Şube A", "percentage": 35.5},
                {"branch": "Şube B", "percentage": 28.3},
                {"branch": "Şube C", "percentage": 20.1},
                {"branch": "Şube D", "percentage": 16.1},
            ],
            "expected_chart": "pie_chart",
            "expected_needs_graph": True
        },
        {
            "name": "No Query Type (Fallback)",
            "query_type": None,
            "user_query": "Verilerimi göster",
            "results": [
                {"item": "A", "value": 100},
                {"item": "B", "value": 200},
            ],
            "expected_chart": "bar_chart",  # Data shape fallback
            "expected_needs_graph": True
        },
        {
            "name": "User Override (Explicit Request)",
            "query_type": "ranking",
            "user_query": "En çok satan 10 ürünü pasta grafiği olarak göster",
            "results": [
                {"product": "Ürün A", "sales": 1000},
                {"product": "Ürün B", "sales": 800},
            ],
            "expected_chart": "pie_chart",  # User override
            "expected_needs_graph": True
        }
    ]

    passed = 0
    failed = 0

    for i, test in enumerate(test_cases, 1):
        print(f"\n--- Test {i}: {test['name']} ---")
        print(f"Query: {test['user_query']}")
        print(f"Query Type: {test['query_type']}")

        # Create test state
        state = ReportState(
            messages=[HumanMessage(content=test['user_query'])],
            user_query=test['user_query'],
            query_type=test['query_type'],
            text2sql_output={"results": test['results']},
            query_history=[],
            active_query_context=None
        )

        # Run decide_visualization_node
        result = await decide_visualization_node(state)
        viz_decision = result.get("_viz_decision", {})

        # Check results
        chart_type = viz_decision.get("chart_type") or viz_decision.get("output_type")
        needs_graph = viz_decision.get("needs_graph", False)
        reasoning = viz_decision.get("reasoning", "")
        query_type_driven = viz_decision.get("query_type_driven", False)

        print(f"Result:")
        print(f"  Chart Type: {chart_type}")
        print(f"  Needs Graph: {needs_graph}")
        print(f"  Query Type Driven: {query_type_driven}")
        print(f"  Reasoning: {reasoning}")

        # Validate
        success = True
        if chart_type != test["expected_chart"]:
            print(f"  [X] FAIL: Expected {test['expected_chart']}, got {chart_type}")
            success = False
        if needs_graph != test["expected_needs_graph"]:
            print(f"  [X] FAIL: Expected needs_graph={test['expected_needs_graph']}, got {needs_graph}")
            success = False

        if success:
            print(f"  [PASS]")
            passed += 1
        else:
            failed += 1

    # Summary
    print("\n" + "=" * 80)
    print(f"PHASE 2 TEST SUMMARY")
    print("=" * 80)
    print(f"Total Tests: {len(test_cases)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success Rate: {passed / len(test_cases) * 100:.1f}%")

    if failed == 0:
        print("\n[SUCCESS] ALL TESTS PASSED - Phase 2 Implementation Successful!")
    else:
        print(f"\n[FAIL] {failed} tests failed - Review implementation")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(test_phase2_visualization())
    exit(0 if success else 1)
