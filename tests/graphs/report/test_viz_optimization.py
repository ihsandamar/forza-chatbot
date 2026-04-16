"""Tests for visualization memory optimizations."""

import pytest


@pytest.mark.asyncio
async def test_response_builder_excludes_full_data():
    """visualization_output should NOT contain full results (memory optimization)."""
    from src.graphs.report_agent.subagents.visualization_v2.nodes import response_builder_node

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
