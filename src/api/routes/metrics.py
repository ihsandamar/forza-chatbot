"""
Metrics API Endpoints

Phase 4: Real-time performance monitoring and statistics.

Features:
- Cache statistics (hit rates, levels)
- Active table tracking
- Session-level metrics
- Performance monitoring

Endpoints:
- GET /metrics/cache/stats: Cache statistics
- GET /metrics/tables/active: Active tables list
- GET /metrics/sessions/{session_id}: Session-level metrics
- GET /metrics/performance/summary: Performance summary
"""

import logging
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException

from src.graphs.generic_text2sql.table_registry import get_table_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])


# =============================================================================
# IN-MEMORY METRICS STORAGE
# =============================================================================

# Store session-level metrics in memory
# In production, this should be persisted to a database
_metrics_store: Dict[str, List[Dict[str, Any]]] = {}


def store_session_metrics(session_id: str, metrics: Dict[str, Any]):
    """
    Store metrics for a session.

    Args:
        session_id: Session identifier
        metrics: Metrics dictionary to store
    """
    if session_id not in _metrics_store:
        _metrics_store[session_id] = []

    _metrics_store[session_id].append({
        **metrics,
        "timestamp": time.time()
    })

    # Keep only last 100 queries per session
    if len(_metrics_store[session_id]) > 100:
        _metrics_store[session_id] = _metrics_store[session_id][-100:]


# =============================================================================
# CACHE ENDPOINTS
# =============================================================================

@router.get("/cache/stats")
async def get_cache_stats() -> Dict[str, Any]:
    """
    Get cache statistics.

    Returns:
        Cache hit rates, levels, and performance metrics
    """
    logger.info("[METRICS_API] Getting cache stats")

    try:
        cache = None  # TODO: conversational_cache removed with legacy report module

        if not cache:
            return {
                "status": "not_initialized",
                "message": "Conversational cache not initialized"
            }

        stats = cache.get_stats()

        return {
            "status": "active",
            **stats,
            "thresholds": {
                "session_threshold": cache.session_threshold,
                "global_threshold": cache.global_threshold
            },
            "ttl": {
                "session_ttl": cache.session_ttl,
                "global_ttl": cache.global_ttl
            }
        }

    except Exception as e:
        logger.error(f"[METRICS_API] Error getting cache stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get cache stats: {str(e)}"
        )


@router.post("/cache/reset")
async def reset_cache_stats() -> Dict[str, str]:
    """
    Reset cache statistics (not cache contents).

    Returns:
        Success message
    """
    logger.info("[METRICS_API] Resetting cache stats")

    try:
        cache = None  # TODO: conversational_cache removed with legacy report module

        if not cache:
            raise HTTPException(
                status_code=404,
                detail="Cache not initialized"
            )

        # Reset stats
        cache.stats = {
            "session_exact_hits": 0,
            "session_semantic_hits": 0,
            "global_hits": 0,
            "misses": 0,
            "total_requests": 0,
            "invalidations": 0
        }

        logger.info("[METRICS_API] Cache stats reset successfully")
        return {"status": "success", "message": "Cache statistics reset"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[METRICS_API] Error resetting cache stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset cache stats: {str(e)}"
        )


# =============================================================================
# TABLE ENDPOINTS
# =============================================================================

@router.get("/tables/active")
async def get_active_tables() -> Dict[str, Any]:
    """
    Get currently active tables.

    Returns:
        List of active tables with metadata
    """
    logger.info("[METRICS_API] Getting active tables")

    try:
        registry = get_table_registry()
        all_tables = await registry.get_all_tables()

        tables_info = [
            {
                "session_id": meta.session_id,
                "table_name": meta.table_name,
                "created_at": meta.created_at,
                "last_accessed_at": meta.last_accessed_at,
                "age_seconds": meta.age_seconds(),
                "ttl_remaining_seconds": meta.ttl_remaining(),
                "query_count": meta.query_count,
                "document_count": meta.document_count,
                "is_expired": meta.is_expired()
            }
            for meta in all_tables
        ]

        # Separate active and expired
        active = [t for t in tables_info if not t["is_expired"]]
        expired = [t for t in tables_info if t["is_expired"]]

        registry_stats = registry.get_stats()

        return {
            "total_tables": len(tables_info),
            "active_count": len(active),
            "expired_count": len(expired),
            "active_tables": active,
            "expired_tables": expired,
            "stats": registry_stats
        }

    except Exception as e:
        logger.error(f"[METRICS_API] Error getting active tables: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get active tables: {str(e)}"
        )


@router.post("/tables/cleanup")
async def trigger_table_cleanup(dry_run: bool = False) -> Dict[str, Any]:
    """
    Trigger immediate table cleanup.

    Args:
        dry_run: If True, only report what would be cleaned up

    Returns:
        List of cleaned up tables
    """
    logger.info(f"[METRICS_API] Triggering table cleanup (dry_run={dry_run})")

    try:
        import os
        db_connection_string = os.getenv("DATABASE_URL")

        if not db_connection_string:
            raise HTTPException(
                status_code=500,
                detail="DATABASE_URL not configured"
            )

        registry = get_table_registry()
        cleaned_tables = await registry.cleanup_expired(db_connection_string, dry_run=dry_run)

        return {
            "status": "success",
            "dry_run": dry_run,
            "cleaned_count": len(cleaned_tables),
            "cleaned_tables": cleaned_tables
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[METRICS_API] Error during table cleanup: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cleanup tables: {str(e)}"
        )


# =============================================================================
# SESSION ENDPOINTS
# =============================================================================

@router.get("/sessions/{session_id}")
async def get_session_metrics(session_id: str) -> Dict[str, Any]:
    """
    Get performance metrics for a session.

    Args:
        session_id: Session identifier

    Returns:
        Session metrics including queries, latency, cache hits
    """
    logger.info(f"[METRICS_API] Getting metrics for session: {session_id}")

    try:
        metrics = _metrics_store.get(session_id, [])

        if not metrics:
            raise HTTPException(
                status_code=404,
                detail=f"No metrics found for session {session_id}"
            )

        # Calculate statistics
        total_queries = len(metrics)
        total_duration = sum(m.get("total_duration_ms", 0) for m in metrics)
        avg_latency = total_duration / total_queries if total_queries > 0 else 0

        total_tokens = sum(m.get("token_usage", {}).get("total", 0) for m in metrics)
        avg_tokens = total_tokens / total_queries if total_queries > 0 else 0

        cache_hits = sum(1 for m in metrics if m.get("cache_stats", {}).get("hits", 0) > 0)
        cache_hit_rate = cache_hits / total_queries if total_queries > 0 else 0

        return {
            "session_id": session_id,
            "total_queries": total_queries,
            "total_duration_ms": total_duration,
            "avg_latency_ms": avg_latency,
            "total_tokens": total_tokens,
            "avg_tokens_per_query": avg_tokens,
            "cache_hit_rate": cache_hit_rate,
            "queries": metrics
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[METRICS_API] Error getting session metrics: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get session metrics: {str(e)}"
        )


@router.get("/sessions")
async def get_all_sessions() -> Dict[str, Any]:
    """
    Get list of all sessions with metrics.

    Returns:
        List of sessions with summary statistics
    """
    logger.info("[METRICS_API] Getting all sessions")

    try:
        sessions_summary = []

        for session_id, metrics in _metrics_store.items():
            if not metrics:
                continue

            total_queries = len(metrics)
            total_duration = sum(m.get("total_duration_ms", 0) for m in metrics)
            avg_latency = total_duration / total_queries if total_queries > 0 else 0

            sessions_summary.append({
                "session_id": session_id,
                "query_count": total_queries,
                "avg_latency_ms": avg_latency,
                "last_query_time": metrics[-1].get("timestamp") if metrics else None
            })

        return {
            "total_sessions": len(sessions_summary),
            "sessions": sorted(sessions_summary, key=lambda s: s.get("last_query_time", 0), reverse=True)
        }

    except Exception as e:
        logger.error(f"[METRICS_API] Error getting all sessions: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get sessions: {str(e)}"
        )


# =============================================================================
# PERFORMANCE ENDPOINTS
# =============================================================================

@router.get("/performance/summary")
async def get_performance_summary() -> Dict[str, Any]:
    """
    Get overall performance summary.

    Returns:
        Aggregated performance metrics across all sessions
    """
    logger.info("[METRICS_API] Getting performance summary")

    try:
        # Aggregate across all sessions
        all_metrics = []
        for metrics in _metrics_store.values():
            all_metrics.extend(metrics)

        if not all_metrics:
            return {
                "status": "no_data",
                "message": "No metrics collected yet"
            }

        total_queries = len(all_metrics)
        total_duration = sum(m.get("total_duration_ms", 0) for m in all_metrics)
        avg_latency = total_duration / total_queries if total_queries > 0 else 0

        total_tokens = sum(m.get("token_usage", {}).get("total", 0) for m in all_metrics)
        avg_tokens = total_tokens / total_queries if total_queries > 0 else 0

        # Cache statistics
        cache_hits = sum(m.get("cache_stats", {}).get("hits", 0) for m in all_metrics)
        cache_misses = sum(m.get("cache_stats", {}).get("misses", 0) for m in all_metrics)
        cache_requests = cache_hits + cache_misses
        cache_hit_rate = cache_hits / cache_requests if cache_requests > 0 else 0

        # Node timing statistics
        all_node_timings = {}
        for m in all_metrics:
            for node, duration in m.get("node_timings", {}).items():
                if node not in all_node_timings:
                    all_node_timings[node] = []
                all_node_timings[node].append(duration)

        avg_node_timings = {
            node: sum(durations) / len(durations)
            for node, durations in all_node_timings.items()
        }

        return {
            "status": "active",
            "total_queries": total_queries,
            "total_duration_ms": total_duration,
            "avg_latency_ms": avg_latency,
            "total_tokens": total_tokens,
            "avg_tokens_per_query": avg_tokens,
            "cache_stats": {
                "hits": cache_hits,
                "misses": cache_misses,
                "hit_rate": cache_hit_rate
            },
            "avg_node_timings": avg_node_timings,
            "total_sessions": len(_metrics_store)
        }

    except Exception as e:
        logger.error(f"[METRICS_API] Error getting performance summary: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get performance summary: {str(e)}"
        )


# =============================================================================
# EXPORT FUNCTION
# =============================================================================

def get_metrics_storage():
    """Get metrics storage for external access."""
    return _metrics_store
