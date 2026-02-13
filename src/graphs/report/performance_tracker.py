"""
Performance Tracker for Report Graph

⚠️ DEPRECATED: This module is currently not used in the report graph.
The PerformanceTracker was designed but never integrated into the node execution flow.

Phase 4: Real-time metrics collection for monitoring and optimization.

Features:
- Node-level timing with millisecond precision
- Token usage tracking per node
- Cache hit tracking
- Error tracking
- Summary statistics

Metrics Collected:
- Node execution time
- Total graph execution time
- Token usage (input, output, total)
- Cache hits/misses
- Errors and failures

Usage:
    tracker = PerformanceTracker()
    start = tracker.start_node("classify_intent")
    # ... node execution ...
    tracker.end_node("classify_intent", start, token_usage={...}, cache_hit=True)
    summary = tracker.get_summary()
"""

import logging
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# =============================================================================
# NODE METRICS
# =============================================================================

@dataclass
class NodeMetrics:
    """Metrics for a single node execution."""
    node_name: str
    start_time: float
    end_time: float
    duration_ms: float
    token_usage: Dict[str, int] = field(default_factory=dict)
    cache_hit: bool = False
    cache_level: Optional[str] = None  # "session_exact", "session_semantic", "global", "miss"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "node_name": self.node_name,
            "duration_ms": self.duration_ms,
            "token_usage": self.token_usage,
            "cache_hit": self.cache_hit,
            "cache_level": self.cache_level,
            "error": self.error
        }


# =============================================================================
# PERFORMANCE TRACKER
# =============================================================================

class PerformanceTracker:
    """
    Track performance metrics for graph execution.

    Collects node-level timing, token usage, and cache statistics.
    """

    def __init__(self):
        """Initialize performance tracker."""
        self.metrics: List[NodeMetrics] = []
        self.start_time = time.time()
        self.end_time: Optional[float] = None

        logger.debug("[PERF_TRACKER] Initialized")

    def start_node(self, node_name: str) -> float:
        """
        Start timing a node execution.

        Args:
            node_name: Name of the node

        Returns:
            Start timestamp (for end_node call)
        """
        start = time.time()
        logger.debug(f"[PERF_TRACKER] Started {node_name}")
        return start

    def end_node(
        self,
        node_name: str,
        start_time: float,
        token_usage: Optional[Dict[str, int]] = None,
        cache_hit: bool = False,
        cache_level: Optional[str] = None,
        error: Optional[str] = None
    ):
        """
        End timing a node execution.

        Args:
            node_name: Name of the node
            start_time: Start timestamp from start_node
            token_usage: Token usage dict with "input", "output", "total" keys
            cache_hit: Whether this was a cache hit
            cache_level: Cache level if cache hit (session_exact, session_semantic, global)
            error: Error message if node failed
        """
        end = time.time()
        duration_ms = (end - start_time) * 1000

        metrics = NodeMetrics(
            node_name=node_name,
            start_time=start_time,
            end_time=end,
            duration_ms=duration_ms,
            token_usage=token_usage or {},
            cache_hit=cache_hit,
            cache_level=cache_level,
            error=error
        )

        self.metrics.append(metrics)

        log_msg = f"[PERF_TRACKER] {node_name}: {duration_ms:.1f}ms"
        if cache_hit:
            log_msg += f" (cache hit: {cache_level})"
        if token_usage:
            log_msg += f" (tokens: {token_usage.get('total', 0)})"
        if error:
            log_msg += f" (error: {error[:50]}...)"

        logger.debug(log_msg)

    def finish(self):
        """Mark graph execution as finished."""
        self.end_time = time.time()
        total_duration = (self.end_time - self.start_time) * 1000
        logger.debug(f"[PERF_TRACKER] Graph execution complete: {total_duration:.1f}ms")

    def get_summary(self) -> Dict[str, Any]:
        """
        Get performance summary.

        Returns:
            Dictionary with summary statistics
        """
        end_time = self.end_time or time.time()
        total_duration_ms = (end_time - self.start_time) * 1000

        # Node timings
        node_timings = {m.node_name: m.duration_ms for m in self.metrics}

        # Token usage
        total_input_tokens = sum(m.token_usage.get("input", 0) for m in self.metrics)
        total_output_tokens = sum(m.token_usage.get("output", 0) for m in self.metrics)
        total_tokens = sum(m.token_usage.get("total", 0) for m in self.metrics)

        # Cache statistics
        cache_hits = sum(1 for m in self.metrics if m.cache_hit)
        cache_misses = sum(1 for m in self.metrics if not m.cache_hit and m.cache_level == "miss")

        # Cache level breakdown
        cache_levels = {}
        for m in self.metrics:
            if m.cache_hit and m.cache_level:
                cache_levels[m.cache_level] = cache_levels.get(m.cache_level, 0) + 1

        # Errors
        errors = [
            {"node": m.node_name, "error": m.error}
            for m in self.metrics if m.error
        ]

        return {
            "total_duration_ms": total_duration_ms,
            "node_count": len(self.metrics),
            "node_timings": node_timings,
            "token_usage": {
                "input": total_input_tokens,
                "output": total_output_tokens,
                "total": total_tokens
            },
            "cache_stats": {
                "hits": cache_hits,
                "misses": cache_misses,
                "hit_rate": cache_hits / (cache_hits + cache_misses) if (cache_hits + cache_misses) > 0 else 0.0,
                "by_level": cache_levels
            },
            "errors": errors,
            "error_count": len(errors)
        }

    def get_detailed_metrics(self) -> List[Dict[str, Any]]:
        """
        Get detailed node-level metrics.

        Returns:
            List of node metrics as dictionaries
        """
        return [m.to_dict() for m in self.metrics]

    def get_slowest_nodes(self, top_n: int = 5) -> List[Dict[str, Any]]:
        """
        Get slowest nodes.

        Args:
            top_n: Number of top slowest nodes to return

        Returns:
            List of slowest node metrics
        """
        sorted_metrics = sorted(self.metrics, key=lambda m: m.duration_ms, reverse=True)
        return [
            {
                "node_name": m.node_name,
                "duration_ms": m.duration_ms,
                "cache_hit": m.cache_hit
            }
            for m in sorted_metrics[:top_n]
        ]

    def get_token_breakdown(self) -> Dict[str, Dict[str, int]]:
        """
        Get token usage breakdown by node.

        Returns:
            Dictionary mapping node names to token usage
        """
        breakdown = {}
        for m in self.metrics:
            if m.token_usage:
                breakdown[m.node_name] = m.token_usage
        return breakdown

    def __repr__(self):
        summary = self.get_summary()
        return (
            f"PerformanceTracker("
            f"duration={summary['total_duration_ms']:.1f}ms, "
            f"nodes={summary['node_count']}, "
            f"tokens={summary['token_usage']['total']}, "
            f"cache_hits={summary['cache_stats']['hits']})"
        )


# =============================================================================
# CONTEXT MANAGER FOR NODE TIMING
# =============================================================================

class NodeTimer:
    """
    Context manager for timing node execution.

    Usage:
        with NodeTimer(tracker, "node_name") as timer:
            # ... node execution ...
            timer.set_token_usage({"input": 100, "output": 50, "total": 150})
            timer.set_cache_hit(True, "session_exact")
    """

    def __init__(self, tracker: PerformanceTracker, node_name: str):
        """
        Initialize node timer.

        Args:
            tracker: PerformanceTracker instance
            node_name: Name of the node
        """
        self.tracker = tracker
        self.node_name = node_name
        self.start_time: Optional[float] = None
        self.token_usage: Optional[Dict[str, int]] = None
        self.cache_hit = False
        self.cache_level: Optional[str] = None
        self.error: Optional[str] = None

    def __enter__(self):
        """Start timing."""
        self.start_time = self.tracker.start_node(self.node_name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """End timing and record metrics."""
        if exc_val:
            # Exception occurred
            self.error = str(exc_val)

        self.tracker.end_node(
            node_name=self.node_name,
            start_time=self.start_time,
            token_usage=self.token_usage,
            cache_hit=self.cache_hit,
            cache_level=self.cache_level,
            error=self.error
        )

        # Don't suppress exception
        return False

    def set_token_usage(self, token_usage: Dict[str, int]):
        """Set token usage for this node."""
        self.token_usage = token_usage

    def set_cache_hit(self, cache_hit: bool, cache_level: Optional[str] = None):
        """Set cache hit status."""
        self.cache_hit = cache_hit
        self.cache_level = cache_level
