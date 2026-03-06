"""Tests for visualization memory optimizations."""

import pytest


@pytest.mark.asyncio
async def test_response_builder_excludes_full_data():
    """visualization_output should NOT contain full results (memory optimization)."""
    from src.graphs.report_agent.subagents.visualization.nodes import response_builder_node

    state = {
        "results": [{"col": i} for i in range(100)],
        "viz_decision": {"chart_type": "bar_chart", "needs_graph": True},
        "data_profile": {"row_count": 100, "column_count": 1},
        "plotly_html_snippet": "<div>plotly</div>",
    }
    output = await response_builder_node(state)
    viz = output["visualization_output"]

    # data key should not exist — it was dead weight
    assert "data" not in viz
    # Other fields must still be present
    assert viz["needs_graph"] is True
    assert viz["chart_type"] == "bar_chart"
    assert viz["plotly_html_snippet"] == "<div>plotly</div>"
    assert "summary" in viz


def test_execute_plotly_code_caps_traces():
    """_execute_plotly_code should cap traces at MAX_TRACES to prevent HTML bloat."""
    from src.graphs.report_agent.subagents.visualization.nodes import _execute_plotly_code

    # Generate code that creates 100 individual traces
    code = """
fig = go.Figure()
for i in range(100):
    fig.add_trace(go.Bar(x=[i], y=[i], name=f"trace_{i}"))
fig.update_layout(title="Test", autosize=True)
"""
    data = [{"x": i, "y": i} for i in range(100)]
    html = _execute_plotly_code(code, data)

    # HTML should be generated but with capped traces
    assert "plotly" in html.lower() or "<div" in html
    # We can't easily check trace count in HTML, but we verify it doesn't error
    # and the HTML size is reasonable (< 200KB for capped traces)
    assert len(html) < 200_000, f"HTML too large: {len(html)} chars — traces likely not capped"
