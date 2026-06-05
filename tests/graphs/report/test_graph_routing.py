"""Tests for report agent graph routing pure functions."""


def test_intent_router_new_query():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "NEW_QUERY"}) == "query_clarifier"


def test_intent_router_modify_query():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "MODIFY_QUERY"}) == "query_clarifier"


def test_intent_router_vague_query_first_entry():
    from src.graphs.report_agent.graph import _intent_router
    state = {"intent_type": "VAGUE_QUERY", "_clarification_count": 0}
    assert _intent_router(state) == "query_clarifier"


def test_intent_router_vague_query_no_count_key():
    """_clarification_count absent defaults to 0 — still goes to clarifier."""
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "VAGUE_QUERY"}) == "query_clarifier"


def test_intent_router_vague_query_reentry_skips_clarifier():
    """VAGUE_QUERY re-entry from report_chat loop should skip clarifier."""
    from src.graphs.report_agent.graph import _intent_router
    state = {"intent_type": "VAGUE_QUERY", "_clarification_count": 1}
    assert _intent_router(state) == "report_chat"


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
    """Bilinmeyen intent → query_clarifier."""
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({}) == "query_clarifier"


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


def test_visualization_router_wants_visualization():
    from src.graphs.report_agent.graph import _visualization_router
    assert _visualization_router({"wants_visualization": True}) == "visualization"


def test_visualization_router_no_visualization():
    from src.graphs.report_agent.graph import _visualization_router
    assert _visualization_router({"wants_visualization": False}) == "build_response"
