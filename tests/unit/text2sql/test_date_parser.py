import pytest
from datetime import date


def test_son_3_ay_no_breakdown():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="son 3 ay", breakdown=False)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "relative"
    assert dd.unit == "month"
    assert dd.amount == -3
    assert gran is None


def test_son_1_ay_breakdown_returns_monthly():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="son 1 ay", breakdown=True)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "relative"
    assert gran == "monthly"


def test_bu_yil():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="bu yıl", breakdown=False)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "current_period"
    assert dd.period == "year"
    assert gran is None


def test_bu_ay_breakdown_returns_monthly():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="bu ay", breakdown=True)
    _, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert gran == "monthly"


def test_gecen_yil():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="geçen yıl", breakdown=False)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "relative"
    assert dd.unit == "year"
    assert dd.amount == -1
    assert gran is None


def test_exact_year():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="2024", breakdown=False)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "exact"
    assert dd.value == "2024-01-01"
    assert gran is None


def test_month_name_year():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="ocak 2024", breakdown=False)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "exact"
    assert dd.value == "2024-01-01"


def test_day_month():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="15 mart", breakdown=False)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.type == "exact"
    assert dd.value == "2026-03-15"


def test_unknown_format_raises_semantic_extraction_error():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    from src.graphs.report_agent.subagents.text2sql.exceptions import SemanticExtractionError
    st = SemanticTime(raw_text="gelecek çeyrek", breakdown=False)
    with pytest.raises(SemanticExtractionError):
        parse_semantic_time(st, date(2026, 4, 21))


def test_son_hafta():
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="son 2 hafta", breakdown=True)
    dd, gran = parse_semantic_time(st, date(2026, 4, 21))
    assert dd.unit == "week"
    assert dd.amount == -2
    assert gran == "weekly"


def test_granularity_field_overrides_period_unit():
    """st.granularity verilmişse period biriminden türetilen değer ezilmeli."""
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    # "son 1 senede" normalde yearly — ama granularity="monthly" → monthly
    st = SemanticTime(raw_text="son 1 senede", breakdown=True, granularity="monthly")
    _, gran = parse_semantic_time(st, date(2026, 4, 22))
    assert gran == "monthly"


def test_granularity_field_overrides_for_gecen_yil():
    """'geçen yıl' normalde yearly — granularity='weekly' ile ezilmeli."""
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="geçen yıl", breakdown=True, granularity="weekly")
    _, gran = parse_semantic_time(st, date(2026, 4, 22))
    assert gran == "weekly"


def test_granularity_none_falls_back_to_period_unit():
    """granularity=None olduğunda mevcut period-birim davranışı korunmalı."""
    from src.graphs.report_agent.subagents.text2sql.date_parser import parse_semantic_time
    from src.graphs.report_agent.subagents.text2sql.semantic_models import SemanticTime
    st = SemanticTime(raw_text="son 1 senede", breakdown=True, granularity=None)
    _, gran = parse_semantic_time(st, date(2026, 4, 22))
    assert gran == "yearly"
