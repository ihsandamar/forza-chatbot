from datetime import date

import pytest

# date.today()'u sabitle
FIXED_TODAY = date(2026, 2, 24)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    class FakeDate(date):
        @classmethod
        def today(cls):
            return FIXED_TODAY

    monkeypatch.setattr(
        "src.graphs.report_agent.subagents.text2sql.date_tool.date",
        FakeDate,
    )


from src.graphs.report_agent.subagents.text2sql.date_tool import resolve_date


def test_son_n_yil():
    result = resolve_date.invoke({"expression": "son 1 yılda"})
    assert "OP:>=" in result
    assert "DATEADD(YEAR, -1, '2026-02-24')" in result


def test_son_n_ay():
    result = resolve_date.invoke({"expression": "son 3 ay"})
    assert "DATEADD(MONTH, -3" in result


def test_bu_yil():
    result = resolve_date.invoke({"expression": "bu yıl"})
    assert "2026" in result
    assert "YEAR" in result


def test_gecen_yil():
    result = resolve_date.invoke({"expression": "geçen yıl"})
    assert "2025" in result


def test_ay_yil():
    result = resolve_date.invoke({"expression": "ocak 2024"})
    assert "2024-01-01" in result
    assert "2024-01-31" in result


def test_iso_date():
    result = resolve_date.invoke({"expression": "2024-03-15"})
    assert "2024-03-15" in result


def test_unresolvable():
    result = resolve_date.invoke({"expression": "bilinmeyen ifade"})
    assert "UNRESOLVED" in result
