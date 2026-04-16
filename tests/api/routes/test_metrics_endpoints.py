"""Regression test: working metrics endpoints survive; broken ones are removed."""
import pytest
from unittest.mock import MagicMock, patch


def test_cache_stats_endpoint_removed():
    """GET /metrics/cache/stats must be gone — it always returned not_initialized."""
    from src.api.routes.metrics import router
    routes = [r.path for r in router.routes]
    assert "/metrics/cache/stats" not in routes, (
        "GET /metrics/cache/stats was permanently broken (cache=None) and should be removed"
    )


def test_cache_reset_endpoint_removed():
    """POST /metrics/cache/reset must be gone — it always raised HTTPException(404)."""
    from src.api.routes.metrics import router
    routes = [r.path for r in router.routes]
    assert "/metrics/cache/reset" not in routes, (
        "POST /metrics/cache/reset was permanently broken (cache=None) and should be removed"
    )


def test_sessions_endpoint_still_exists():
    """GET /metrics/sessions must still exist."""
    from src.api.routes.metrics import router
    routes = [r.path for r in router.routes]
    assert any("sessions" in r for r in routes), (
        "GET /metrics/sessions should still exist after cleanup"
    )
