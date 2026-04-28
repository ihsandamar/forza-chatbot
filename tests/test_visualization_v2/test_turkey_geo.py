"""Tests for Turkey map utility functions."""


def test_detect_city_column_finds_branchcityname():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import detect_city_column
    assert detect_city_column(["BranchCityName", "RowAmount"]) == "BranchCityName"


def test_detect_city_column_finds_sehir():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import detect_city_column
    assert detect_city_column(["SehirAdi", "Tutar"]) == "SehirAdi"


def test_detect_city_column_finds_cityname():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import detect_city_column
    assert detect_city_column(["CityName", "Revenue"]) == "CityName"


def test_detect_city_column_returns_none_for_no_city():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import detect_city_column
    assert detect_city_column(["BranchName", "ProductName", "RowAmount"]) is None


def test_detect_city_column_returns_none_for_empty():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import detect_city_column
    assert detect_city_column([]) is None


def test_normalize_city_name_strips_turkish_diacritics():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import normalize_city_name
    assert normalize_city_name("İstanbul") == "istanbul"
    assert normalize_city_name("Şanlıurfa") == "sanliurfa"
    assert normalize_city_name("Muğla") == "mugla"


def test_normalize_city_name_lowercases():
    from src.graphs.report_agent.subagents.visualization_v2.turkey_geo import normalize_city_name
    assert normalize_city_name("ANKARA") == "ankara"
    assert normalize_city_name("Ankara") == "ankara"
