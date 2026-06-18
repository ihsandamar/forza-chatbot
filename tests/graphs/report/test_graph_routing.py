"""Tests for report agent graph routing pure functions."""


def test_intent_router_new_query():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "NEW_QUERY"}) == "text2sql"


def test_intent_router_modify_query():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "MODIFY_QUERY"}) == "modify_sql"


def test_intent_router_use_result_revisualize():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "USE_RESULT", "use_result_type": "revisualize"}) == "visualization"


def test_intent_router_use_result_new_query():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "USE_RESULT", "use_result_type": "new_query"}) == "extract_entity"


def test_intent_router_use_result_compute():
    """compute → compute_results (YENİ)."""
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "USE_RESULT", "use_result_type": "compute"}) == "compute_results"


def test_intent_router_use_result_modify_context():
    """modify_context → extract_entity gibi davranır (YENİ)."""
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "USE_RESULT", "use_result_type": "modify_context"}) == "extract_entity"


def test_intent_router_fallback():
    """Bilinmeyen intent → text2sql."""
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({}) == "text2sql"


def test_after_extract_entity_router_new_query():
    from src.graphs.report_agent.graph import _after_extract_entity_router
    assert _after_extract_entity_router({"use_result_type": "new_query"}) == "text2sql"


def test_after_extract_entity_router_modify_context():
    """modify_context → modify_sql (YENİ)."""
    from src.graphs.report_agent.graph import _after_extract_entity_router
    assert _after_extract_entity_router({"use_result_type": "modify_context"}) == "modify_sql"


def test_after_extract_entity_router_default():
    """use_result_type yoksa text2sql."""
    from src.graphs.report_agent.graph import _after_extract_entity_router
    assert _after_extract_entity_router({}) == "text2sql"


def test_after_visualization_router_wants_export():
    from src.graphs.report_agent.graph import _after_visualization_router
    assert _after_visualization_router({"wants_export": True}) == "export"


def test_after_visualization_router_no_export():
    from src.graphs.report_agent.graph import _after_visualization_router
    assert _after_visualization_router({"wants_export": False}) == "build_response"


def test_intent_router_export_request():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "EXPORT_REQUEST"}) == "export"


def test_after_hitl_check_router_wants_export():
    from src.graphs.report_agent.graph import _after_hitl_check_router
    assert _after_hitl_check_router({"wants_export": True}) == "export"
