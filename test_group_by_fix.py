"""
GROUP BY Fix Validation Test

Test that query type patterns now include GROUP BY guidance.
"""

from src.graphs.report.query_type_patterns import get_pattern


def test_group_by_guidance():
    """Test that all aggregation-based query types have GROUP BY guidance."""

    print("=" * 80)
    print("GROUP BY FIX VALIDATION TEST")
    print("=" * 80)

    # Query types that require aggregations (and therefore GROUP BY)
    aggregation_types = [
        "ranking",
        "comparison",
        "aggregation",
        "time_series",
        "time_series_comparison",
        "distribution"
    ]

    passed = 0
    failed = 0

    for query_type in aggregation_types:
        print(f"\n--- Testing: {query_type} ---")

        pattern = get_pattern(query_type)

        if not pattern:
            print(f"  [FAIL] Pattern not found")
            failed += 1
            continue

        # Check if GROUP BY is mentioned in requirements
        requirements = pattern.get("sql_requirements", [])
        hints = pattern.get("sql_hints", [])

        has_group_by_requirement = any(
            "GROUP BY" in req.upper() for req in requirements
        )

        has_group_by_hint = any(
            "GROUP BY" in hint.upper() or "group_by" in hint.lower()
            for hint in hints
        )

        # Check for critical warnings
        has_critical_warning = any(
            "KRİTİK" in hint or "MUTLAKA" in hint or "ZORUNLU" in hint
            for hint in hints + requirements
        )

        print(f"  Description: {pattern['description']}")
        print(f"  Has GROUP BY in requirements: {has_group_by_requirement}")
        print(f"  Has GROUP BY in hints: {has_group_by_hint}")
        print(f"  Has critical warning: {has_critical_warning}")

        # Validation
        if has_group_by_requirement and has_critical_warning:
            print(f"  [PASS] GROUP BY guidance is clear and emphatic")
            passed += 1
        elif has_group_by_requirement:
            print(f"  [WARN] GROUP BY mentioned but no critical warning")
            passed += 1
        else:
            print(f"  [FAIL] GROUP BY guidance missing or unclear")
            failed += 1

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Total Tests: {len(aggregation_types)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success Rate: {passed / len(aggregation_types) * 100:.1f}%")

    if failed == 0:
        print("\n[SUCCESS] All query types have GROUP BY guidance!")
        print("The SQL error should now be prevented by clear LLM instructions.")
    else:
        print(f"\n[FAIL] {failed} query types need GROUP BY guidance")

    return failed == 0


if __name__ == "__main__":
    success = test_group_by_guidance()
    exit(0 if success else 1)
