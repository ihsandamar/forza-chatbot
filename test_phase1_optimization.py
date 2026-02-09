"""
Phase 1 Optimization Test Script

Tests the three Phase 1 optimizations:
1. Semantic cache enabled by default
2. Fast-path intent classification
3. Parallel business insights + viz decision

Usage:
    python test_phase1_optimization.py
"""

import asyncio
import time
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_fast_path_classification():
    """Test fast-path intent classification patterns."""
    print("\n" + "="*80)
    print("TEST 1: Fast-Path Intent Classification")
    print("="*80)

    from src.graphs.report.nodes import create_intent_classifier_node
    from src.models.llm import LLM
    from src.graphs.report.state import ReportState
    from langchain_core.messages import HumanMessage

    # Initialize LLM (needed for fallback)
    llm = LLM()
    llm_chat = llm.get_chat()

    # Create classifier node
    classifier_node = create_intent_classifier_node(llm_chat, enable_fast_path=True)

    # Test cases
    test_cases = [
        # Fast-path rollback
        {
            "message": "geri al",
            "expected": "rollback",
            "should_fast_path": True
        },
        {
            "message": "önceki sorguya dön",
            "expected": "rollback",
            "should_fast_path": True
        },
        # Fast-path visualize
        {
            "message": "grafik yap",
            "expected": "visualize",
            "should_fast_path": True
        },
        {
            "message": "bar chart çiz",
            "expected": "visualize",
            "should_fast_path": True
        },
        # Fast-path simple query
        {
            "message": "satışları göster",
            "expected": "new_query",
            "should_fast_path": True
        },
        {
            "message": "müşterileri listele",
            "expected": "new_query",
            "should_fast_path": True
        },
        # Complex query (should use LLM)
        {
            "message": "son 3 ayda istanbul'daki şubelerimizin satış performansını kategorilere göre analiz et",
            "expected": "new_query",
            "should_fast_path": False
        }
    ]

    results = []
    for test in test_cases:
        state: ReportState = {
            "messages": [HumanMessage(content=test["message"])],
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

        start = time.time()
        result = await classifier_node(state)
        elapsed = time.time() - start

        intent_type = result.get("_intent_type")
        reasoning = result.get("_intent_reasoning", "")
        is_fast_path = "Fast path" in reasoning

        success = intent_type == test["expected"] and is_fast_path == test["should_fast_path"]
        results.append({
            "message": test["message"],
            "expected": test["expected"],
            "actual": intent_type,
            "fast_path": is_fast_path,
            "elapsed_ms": elapsed * 1000,
            "success": success
        })

        status = "✓" if success else "✗"
        fp_marker = "⚡" if is_fast_path else "🐌"
        print(f"{status} {fp_marker} [{intent_type}] {test['message'][:50]:50} ({elapsed*1000:.0f}ms)")

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["success"])
    fast_path_count = sum(1 for r in results if r["fast_path"])
    avg_time = sum(r["elapsed_ms"] for r in results) / total

    print(f"\nSummary:")
    print(f"  Total tests: {total}")
    print(f"  Passed: {passed}/{total} ({passed/total*100:.1f}%)")
    print(f"  Fast-path used: {fast_path_count}/{total} ({fast_path_count/total*100:.1f}%)")
    print(f"  Average time: {avg_time:.0f}ms")

    return passed == total


async def test_parallel_execution():
    """Test parallel insights + viz decision execution."""
    print("\n" + "="*80)
    print("TEST 2: Parallel Insights + Viz Decision")
    print("="*80)

    from src.graphs.report.nodes import create_parallel_insights_viz_node
    from src.graphs.report.business_context_tracker import BusinessContextTracker
    from src.graphs.report.report_interpreter import create_report_interpreter
    from src.graphs.report.state import ReportState
    from src.models.llm import LLM
    from langchain_core.messages import HumanMessage

    # Initialize components
    llm = LLM()
    llm_chat = llm.get_chat()

    business_tracker = BusinessContextTracker(llm=llm_chat)
    report_interpreter = create_report_interpreter(llm=llm_chat, use_llm=True)

    # Create parallel node
    parallel_node = create_parallel_insights_viz_node(
        business_tracker=business_tracker,
        report_interpreter=report_interpreter
    )

    # Mock state with sample data
    state: ReportState = {
        "messages": [HumanMessage(content="Show me sales by city")],
        "active_query_context": None,
        "query_history": [],
        "pending_question": None,
        "waiting_for_user_input": False,
        "user_clarification": None,
        "text2sql_output": {
            "results": [
                {"city": "Istanbul", "sales": 1500},
                {"city": "Ankara", "sales": 1200},
                {"city": "Izmir", "sales": 900}
            ],
            "sql_queries": ["SELECT city, SUM(sales) FROM sales GROUP BY city"],
            "error": None
        },
        "visualization_output": None,
        "error": None,
        "no_records_message": None,
        "business_context": None
    }

    print("\nRunning parallel execution...")
    start = time.time()
    result = await parallel_node(state)
    elapsed = time.time() - start

    print(f"\nParallel execution completed in {elapsed:.2f}s")

    # Check results
    has_business_context = "business_context" in result
    has_viz_decision = "_viz_decision" in result

    print(f"\nResults:")
    print(f"  ✓ Business context: {'Yes' if has_business_context else 'No'}")
    print(f"  ✓ Viz decision: {'Yes' if has_viz_decision else 'No'}")

    if has_business_context:
        bc = result["business_context"]
        print(f"  ✓ Key insights: {len(bc.get('key_insights', []))}")

    if has_viz_decision:
        vd = result["_viz_decision"]
        print(f"  ✓ Output type: {vd.get('output_type')}")
        print(f"  ✓ Needs graph: {vd.get('needs_graph')}")

    # Success if both completed and time < 2s (should be ~0.8-1s with parallel)
    success = has_business_context and has_viz_decision and elapsed < 2.0

    status = "✓ PASS" if success else "✗ FAIL"
    print(f"\n{status}: Parallel execution {'succeeded' if success else 'failed'}")

    return success


async def test_semantic_cache():
    """Test semantic cache functionality."""
    print("\n" + "="*80)
    print("TEST 3: Semantic Cache")
    print("="*80)

    from src.graphs.report.semantic_cache import SemanticCache
    from src.models.llm import LLM

    # Initialize cache
    llm = LLM()
    if not hasattr(llm, 'get_embeddings'):
        print("⚠️  Embeddings not available, skipping cache test")
        return True

    embeddings = llm.get_embeddings()
    cache = SemanticCache(
        embeddings=embeddings,
        threshold=0.95,
        ttl=3600,
        max_size=2000
    )

    # Test query
    test_query = "Show me sales by city"

    # Mock compute function
    async def compute_result():
        await asyncio.sleep(0.5)  # Simulate LLM call
        return {"result": "sales data"}

    # First call (cache miss)
    print("\nFirst call (cache miss)...")
    start = time.time()
    result1 = await cache.get_or_compute(test_query, compute_result)
    time1 = time.time() - start
    print(f"  Time: {time1:.2f}s (expected ~0.5s)")

    # Second call (cache hit)
    print("\nSecond call (cache hit)...")
    start = time.time()
    result2 = await cache.get_or_compute(test_query, compute_result)
    time2 = time.time() - start
    print(f"  Time: {time2:.2f}s (expected <0.1s)")

    # Similar query (semantic hit)
    similar_query = "Show me sales data by cities"
    print("\nSimilar query (semantic hit)...")
    start = time.time()
    result3 = await cache.get_or_compute(similar_query, compute_result)
    time3 = time.time() - start
    print(f"  Time: {time3:.2f}s (expected <0.1s)")

    # Get stats
    stats = cache.get_stats()
    print(f"\nCache stats:")
    print(f"  Hits: {stats['hits']}")
    print(f"  Misses: {stats['misses']}")
    print(f"  Hit rate: {stats['hit_rate']:.2%}")
    print(f"  Cache size: {stats['cache_size']}")

    # Success if cache hit is significantly faster
    success = time2 < time1 * 0.3 and stats['hit_rate'] >= 0.5

    status = "✓ PASS" if success else "✗ FAIL"
    print(f"\n{status}: Cache {'working correctly' if success else 'not working as expected'}")

    return success


async def main():
    """Run all tests."""
    print("\n")
    print("="*80)
    print("PHASE 1 OPTIMIZATION TEST SUITE")
    print("="*80)
    print("\nTesting Phase 1 optimizations:")
    print("1. Semantic cache enabled by default")
    print("2. Fast-path intent classification")
    print("3. Parallel business insights + viz decision")

    results = []

    try:
        # Test 1: Fast-path classification
        result1 = await test_fast_path_classification()
        results.append(("Fast-path classification", result1))
    except Exception as e:
        logger.error(f"Test 1 failed: {e}", exc_info=True)
        results.append(("Fast-path classification", False))

    try:
        # Test 2: Parallel execution
        result2 = await test_parallel_execution()
        results.append(("Parallel execution", result2))
    except Exception as e:
        logger.error(f"Test 2 failed: {e}", exc_info=True)
        results.append(("Parallel execution", False))

    try:
        # Test 3: Semantic cache
        result3 = await test_semantic_cache()
        results.append(("Semantic cache", result3))
    except Exception as e:
        logger.error(f"Test 3 failed: {e}", exc_info=True)
        results.append(("Semantic cache", False))

    # Final summary
    print("\n" + "="*80)
    print("FINAL RESULTS")
    print("="*80)

    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {name}")

    total = len(results)
    passed = sum(1 for _, success in results if success)

    print(f"\nOverall: {passed}/{total} tests passed ({passed/total*100:.1f}%)")

    if passed == total:
        print("\n🎉 All Phase 1 optimizations are working correctly!")
    else:
        print("\n⚠️  Some tests failed. Please review the output above.")


if __name__ == "__main__":
    asyncio.run(main())
