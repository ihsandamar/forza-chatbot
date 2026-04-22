import pytest


def test_schema_builder_never_produces_none_value_hint():
    """Integration: schema_builder always sets value_hint on filters — no None slips to value_resolver."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric, SemanticTime, TermMatch
    )
    from datetime import date

    intent = SemanticIntent(
        entities=[
            SemanticEntity(raw_text="Ankara", entity_type="filter_value", column_hint="BranchName"),
            SemanticEntity(raw_text="ürün", entity_type="dimension"),
        ],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        time=SemanticTime(raw_text="son 3 ay", breakdown=False),
        raw_query="Ankara ürünlere göre son 3 ay ciro",
    )
    term_resolution = {
        "Ankara": TermMatch("BranchName", None, 1.0, 0.95),
        "ürün": TermMatch("ProductName", None, 1.0, 0.88),
        "ciro": TermMatch("RowAmount", None, 1.0, 0.92),
    }
    schema = build_query_schema(intent, term_resolution, "LISTING", False, date(2026, 4, 21))

    for f in schema.filters:
        assert f.value_hint is not None, (
            f"SchemaFilter column={f.column!r} operator={f.operator!r} has value_hint=None. "
            "schema_builder must always set value_hint."
        )
