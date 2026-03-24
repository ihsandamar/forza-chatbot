"""Unit tests for _detect_chart_type_from_query deterministic fallback.

Pure function tests — no LLM, no I/O, no async.
"""


def _fn(text):
    from src.graphs.report_agent.nodes import _detect_chart_type_from_query
    return _detect_chart_type_from_query(text)


# --- Exact keyword match ---
def test_sunburst_exact():
    assert _fn("sunburst grafik ver") == "sunburst"

def test_heatmap_exact():
    assert _fn("heatmap göster") == "heatmap"

def test_treemap_exact():
    assert _fn("treemap istiyorum") == "treemap"

def test_bar_chart_turkish():
    assert _fn("çubuk grafik") == "bar_chart"

def test_line_chart_turkish():
    assert _fn("çizgi grafik") == "line_chart"

def test_pie_chart_turkish():
    assert _fn("pasta grafik") == "pie_chart"

def test_scatter_chart_compound():
    assert _fn("scatter chart ver") == "scatter_chart"

def test_bar_chart_compound_english():
    assert _fn("bar chart istiyorum") == "bar_chart"

def test_line_chart_compound_english():
    assert _fn("line chart göster") == "line_chart"

def test_pie_chart_compound_english():
    assert _fn("pie chart ver") == "pie_chart"


# --- Typo tolerance (root cause case) ---
def test_sunbrust_typo():
    """Root cause: 'sunbrust' LLM tarafından resolve edilemiyor — bu test bunu yakalar."""
    assert _fn("sunbrust grafik ver") == "sunburst"

def test_sunbrust_uppercase():
    assert _fn("SUNBRUST GRAFİK") == "sunburst"

def test_sunbrust_in_full_query():
    """Actual failing query from the bug report."""
    q = ("Son 3 aydaki satışları karşılaştır ve bunlar içinde hangi kategoriler "
         "ne kadar satmış onu da gösteren sunbrust grafik ver")
    assert _fn(q) == "sunburst"


# --- Turkish heatmap ---
def test_isı_haritası():
    assert _fn("ısı haritası göster") == "heatmap"


# --- No false positives for bare English words in Turkish text ---
def test_no_false_positive_kabartma():
    """'kabartma' contains 'bar' as substring — must NOT trigger bar_chart."""
    assert _fn("kabartma tekniği") is None

def test_no_false_positive_line_in_turkish():
    """'oline' (as in online) must NOT trigger line_chart."""
    assert _fn("online rapor ver") is None


# --- No match cases ---
def test_no_chart_keyword_returns_none():
    assert _fn("son 3 aydaki satışları göster") is None

def test_empty_string_returns_none():
    assert _fn("") is None

def test_only_whitespace_returns_none():
    assert _fn("   ") is None
