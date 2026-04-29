"""Tests for create_build_response_node — iframe output format + response text."""
import pytest


def _make_chart_state(chart_type: str = "bar_chart", snippet: str = '<div id="x"></div>') -> dict:
    return {
        "results": [{"City": "Ankara", "Amount": 1000}],
        "user_query": "satis raporu",
        "visualization_output": {
            "needs_graph": True,
            "chart_type": chart_type,
            "plotly_html_snippet": snippet,
            "summary": "Test chart",
            "x_field": "City",
            "y_field": "Amount",
            "title": "Test Grafik",
        },
    }


@pytest.mark.asyncio
async def test_build_response_uses_srcdoc():
    """iframe uses srcdoc (embedding) + src data URI (new tab support)."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    result = await node_fn(_make_chart_state())
    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert '<iframe ' in chart_html
    assert 'srcdoc=' in chart_html
    assert 'src="data:text/html' in chart_html


@pytest.mark.asyncio
async def test_build_response_iframe_height_default():
    """Regular charts get 480px height."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    result = await node_fn(_make_chart_state(chart_type="bar_chart"))
    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'height:480px' in chart_html


@pytest.mark.asyncio
async def test_build_response_iframe_height_turkey_map():
    """turkey_map gets 600px height."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    result = await node_fn(_make_chart_state(chart_type="turkey_map"))
    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'height:600px' in chart_html


@pytest.mark.asyncio
async def test_build_response_srcdoc_escaping():
    """Double quotes in snippet must be escaped as &quot; in srcdoc."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    snippet = '<div id="myChart" data-x="a&b" style="color:red"></div>'
    result = await node_fn(_make_chart_state(snippet=snippet))
    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'srcdoc="' in chart_html
    assert '&quot;' in chart_html
    assert '"myChart"' not in chart_html
    assert '&amp;' in chart_html


@pytest.mark.asyncio
async def test_build_response_inner_css_present():
    """Inner HTML must contain responsive CSS for plotly-graph-div."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    result = await node_fn(_make_chart_state())
    chart_html = result["messages"][0].additional_kwargs["chart_html"]
    assert 'plotly-graph-div' in chart_html
    assert '.plotly-graph-div{width:100%' in chart_html


@pytest.mark.asyncio
async def test_build_response_no_graph_falls_back_to_table():
    """When needs_graph is False, markdown table is returned (no iframe)."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    state = {
        "results": [{"Name": "A", "Value": 1}],
        "visualization_output": {"needs_graph": False},
    }
    result = await node_fn(state)
    assert "chart_html" not in result["messages"][0].additional_kwargs
    assert "iframe" not in result["final_response"]
    assert "Name" in result["final_response"]


@pytest.mark.asyncio
async def test_build_response_summary_text_uses_response_builder():
    """AIMessage.content must come from response_builder, not the old hardcoded format."""
    from src.graphs.report_agent.nodes import create_build_response_node
    node_fn = create_build_response_node()
    result = await node_fn(_make_chart_state())
    content = result["messages"][0].content
    # Old hardcoded format must be gone
    assert "Görselleştirme Tipi" not in content
    assert "Grafik Gerekli" not in content
    # New format: insight + metadata from response_builder
    assert "kayıt" in content
