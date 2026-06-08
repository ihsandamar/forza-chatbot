# tests/graphs/report/insight_engine/test_graph_routing.py

def test_intent_router_insight_request():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "INSIGHT_REQUEST"}) == "insight_engine"


def test_intent_router_existing_routes_unchanged():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "NEW_QUERY"}) == "text2sql"
    assert _intent_router({"intent_type": "MODIFY_QUERY"}) == "modify_sql"
    assert _intent_router({"intent_type": "VAGUE_QUERY"}) == "report_chat"
