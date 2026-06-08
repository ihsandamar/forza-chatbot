def test_insight_fields_in_report_state():
    from src.graphs.report_agent.state import ReportState, create_initial_state
    state = create_initial_state()
    assert "comparison_sql" in state
    assert "insight_findings" in state
    assert "insight_output" in state
    assert state["comparison_sql"] is None
    assert state["insight_findings"] is None
    assert state["insight_output"] is None
