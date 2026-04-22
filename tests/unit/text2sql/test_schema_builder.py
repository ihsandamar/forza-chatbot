import pytest
from datetime import date


def _make_tm(col, filter_structured=None, specificity=1.0, similarity=0.9):
    from src.graphs.report_agent.subagents.text2sql.semantic_models import TermMatch
    return TermMatch(column_name=col, filter_structured=filter_structured,
                     specificity=specificity, similarity=similarity)


def test_value_hint_always_set():
    """Every SchemaFilter produced by schema_builder must have value_hint set (not None)."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticIntent, SemanticEntity, SemanticMetric
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="Ankara", entity_type="filter_value", column_hint="BranchName")],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="Ankara şubesi ciro",
    )
    term_resolution = {
        "Ankara": _make_tm("BranchName"),
        "ciro": _make_tm("RowAmount"),
    }
    schema = build_query_schema(intent, term_resolution, "SINGLE", False, date(2026, 4, 21))
    for f in schema.filters:
        assert f.value_hint is not None, f"SchemaFilter for column={f.column} has None value_hint"


def test_comparison_query_generates_IN_not_AND():
    """comparison_value entities with same column → SchemaFilter operator=IN, not two AND= filters."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    intent = SemanticIntent(
        entities=[
            SemanticEntity(raw_text="dürümler", entity_type="comparison_value", column_hint="CategoryName"),
            SemanticEntity(raw_text="içecek", entity_type="comparison_value", column_hint="CategoryName"),
        ],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="dürümler ve içecek karşılaştır",
    )
    term_resolution = {
        "dürümler": _make_tm("CategoryName"),
        "içecek": _make_tm("CategoryName"),
        "ciro": _make_tm("RowAmount"),
    }
    schema = build_query_schema(intent, term_resolution, "COMPARISON", False, date(2026, 4, 21))
    cat_filters = [f for f in schema.filters if f.column == "CategoryName"]
    assert len(cat_filters) == 1, "Expected single IN filter, not two AND= filters"
    assert cat_filters[0].operator == "IN"
    assert set(cat_filters[0].values) == {"dürümler", "içecek"}


def test_monthly_time_series_sets_granularity():
    """SemanticTime(breakdown=True, 'son 1 ay') → time_granularity='monthly'."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticMetric, SemanticTime,
    )
    intent = SemanticIntent(
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        time=SemanticTime(raw_text="son 1 ay", breakdown=True),
        raw_query="aylık ciro son 1 ay",
    )
    schema = build_query_schema(intent, {"ciro": _make_tm("RowAmount")},
                                "TIME_SERIES_COMPARISON", True, date(2026, 4, 21))
    assert schema.time_granularity == "monthly"


def test_intent_time_breakdown_false_overridden_by_query_type_flag():
    """time_breakdown=True at schema_builder level overrides SemanticTime.breakdown=False."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticMetric, SemanticTime,
    )
    intent = SemanticIntent(
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        time=SemanticTime(raw_text="son 3 ay", breakdown=False),
        raw_query="aylık ciro",
    )
    schema = build_query_schema(intent, {"ciro": _make_tm("RowAmount")},
                                "TIME_SERIES_COMPARISON", True, date(2026, 4, 21))
    assert schema.time_granularity == "monthly"


def test_dimension_entity_goes_to_group_by():
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="ürün", entity_type="dimension")],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="ürünlere göre ciro",
    )
    term_resolution = {
        "ürün": _make_tm("ProductName"),
        "ciro": _make_tm("RowAmount"),
    }
    schema = build_query_schema(intent, term_resolution, "LISTING", False, date(2026, 4, 21))
    assert "ProductName" in schema.group_by


def test_filter_term_with_pre_built_filter_structured():
    """TermMatch with filter_structured → SchemaFilter uses filter values, value_hint still set."""
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    filter_structured = {"column": "DocumentTypeIsReturn", "operator": "=", "value": "1"}
    intent = SemanticIntent(
        entities=[SemanticEntity(raw_text="iade", entity_type="filter_value")],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="iade ciro",
    )
    term_resolution = {
        "iade": _make_tm("DocumentTypeIsReturn", filter_structured=filter_structured),
        "ciro": _make_tm("RowAmount"),
    }
    schema = build_query_schema(intent, term_resolution, "SINGLE", False, date(2026, 4, 21))
    return_filters = [f for f in schema.filters if f.column == "DocumentTypeIsReturn"]
    assert len(return_filters) == 1
    assert return_filters[0].value == "1"
    assert return_filters[0].value_hint == "iade"


def test_unresolved_filter_value_without_column_hint_is_skipped():
    """
    term_resolution'da eşleşme yok ve column_hint=None ise,
    filter_value entity'si için SchemaFilter üretilmemeli (raw_text kolon adı olarak kullanılmamalı).
    """
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    intent = SemanticIntent(
        entities=[
            SemanticEntity(raw_text="espresso kategorisi", entity_type="filter_value", column_hint=None),
        ],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="espresso kategorisi ciro",
    )
    # term_resolution'da "espresso kategorisi" yok
    term_resolution = {"ciro": _make_tm("RowAmount")}
    schema = build_query_schema(intent, term_resolution, "SINGLE", False)

    # "espresso kategorisi" kolon adlı bir filter OLMAMALI
    column_names = [f.column for f in schema.filters if f.column != "DocumentDate"]
    assert "espresso kategorisi" not in column_names, (
        "entity.raw_text should NEVER be used as a DB column name"
    )


def test_unresolved_dimension_without_column_hint_is_skipped():
    """
    term_resolution'da eşleşme yok ve column_hint=None ise,
    dimension entity'si group_by'a eklenmemeli.
    """
    from src.graphs.report_agent.subagents.text2sql.schema_builder import build_query_schema
    from src.graphs.report_agent.subagents.text2sql.semantic_models import (
        SemanticIntent, SemanticEntity, SemanticMetric,
    )
    intent = SemanticIntent(
        entities=[
            SemanticEntity(raw_text="bilinmeyen boyut", entity_type="dimension", column_hint=None),
        ],
        metrics=[SemanticMetric(raw_text="ciro", aggregation_hint="SUM")],
        raw_query="bilinmeyen boyut ciro",
    )
    term_resolution = {"ciro": _make_tm("RowAmount")}
    schema = build_query_schema(intent, term_resolution, "LISTING", False)

    assert "bilinmeyen boyut" not in schema.group_by
