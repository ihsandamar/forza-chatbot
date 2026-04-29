"""Tests for build_response_node — iframe output format."""
import pytest


def _make_chart_state(chart_type: str = "bar_chart", snippet: str = '<div id="x"></div>') -> dict:
    return {
        "results": [{"A": 1}],
        "visualization_output": {
            "needs_graph": True,
            "chart_type": chart_type,
            "plotly_html_snippet": snippet,
            "summary": "Test chart",
        },
    }


@pytest.mark.asyncio
async def test_build_response_uses_srcdoc():
    """iframe must use srcdoc, not base64 data URI."""
    from src.graphs.report_agent.nodes import build_response_node

    result = await build_response_node(_make_chart_state())

    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'srcdoc=' in chart_html
    assert 'data:text/html' not in chart_html
    assert 'base64' not in chart_html
    assert '<iframe ' in chart_html


@pytest.mark.asyncio
async def test_build_response_iframe_height_default():
    """Regular charts get 480px height."""
    from src.graphs.report_agent.nodes import build_response_node

    result = await build_response_node(_make_chart_state(chart_type="bar_chart"))

    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'height:480px' in chart_html


@pytest.mark.asyncio
async def test_build_response_iframe_height_turkey_map():
    """turkey_map gets 600px height for extra vertical space."""
    from src.graphs.report_agent.nodes import build_response_node

    result = await build_response_node(_make_chart_state(chart_type="turkey_map"))

    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'height:600px' in chart_html


@pytest.mark.asyncio
async def test_build_response_srcdoc_escaping():
    """Double quotes in the snippet must be escaped as &quot; in srcdoc attribute."""
    from src.graphs.report_agent.nodes import build_response_node

    snippet = '<div id="myChart" data-x="a&b" style="color:red"></div>'
    result = await build_response_node(_make_chart_state(snippet=snippet))

    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    # The " characters in the snippet must appear as &quot; — not raw " — inside the srcdoc value
    assert 'srcdoc="' in chart_html
    assert '&quot;' in chart_html
    # Verify raw unescaped quote is not present
    assert '"myChart"' not in chart_html
    # Verify & is escaped as &amp;
    assert '&amp;' in chart_html


@pytest.mark.asyncio
async def test_build_response_inner_css_present():
    """Inner HTML must contain responsive CSS for plotly-graph-div."""
    from src.graphs.report_agent.nodes import build_response_node

    result = await build_response_node(_make_chart_state())

    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'plotly-graph-div' in chart_html
    assert '.plotly-graph-div{width:100%' in chart_html


@pytest.mark.asyncio
async def test_build_response_no_graph_falls_back_to_table():
    """When needs_graph is False, markdown table is returned (no iframe)."""
    from src.graphs.report_agent.nodes import build_response_node

    state = {
        "results": [{"Name": "A", "Value": 1}],
        "visualization_output": {"needs_graph": False},
    }
    result = await build_response_node(state)

    assert "chart_html" not in result["messages"][0].additional_kwargs
    assert "iframe" not in result["final_response"]
    assert "Name" in result["final_response"]
