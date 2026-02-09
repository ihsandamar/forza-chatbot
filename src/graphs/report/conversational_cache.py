"""
Conversational Semantic Cache with Multi-Level Lookup

Phase 4 enhancement: Session-aware caching with multiple lookup levels:
- Level 1: Session exact match (hash-based, instant)
- Level 2: Session semantic (threshold=0.85, fast)
- Level 3: Global semantic (threshold=0.92, strict)

Features:
- Session isolation for conversational queries
- Multi-level fallback for optimal hit rates
- Session invalidation on delta updates
- Comprehensive statistics tracking

Expected Performance:
- Cache hit rate: 35-50% in conversations
- Level 1 (exact): <1ms
- Level 2 (session semantic): 5-10ms
- Level 3 (global semantic): 10-20ms
"""

import logging
import hashlib
import time
from typing import Any, Callable, Dict, Optional, List, Tuple
from dataclasses import dataclass
import asyncio

import numpy as np
from langchain_core.embeddings import Embeddings

from .semantic_cache import SemanticCache, CacheEntry

logger = logging.getLogger(__name__)


# =============================================================================
# SESSION CACHE ENTRY
# =============================================================================

@dataclass
class SessionCacheEntry:
    """Cache entry for session-specific queries."""
    query: str
    query_hash: str
    embedding: np.ndarray
    result: Any
    timestamp: float
    ttl: int
    access_count: int = 0

    def is_expired(self) -> bool:
        """Check if entry is expired based on TTL."""
        return time.time() - self.timestamp > self.ttl

    def refresh(self):
        """Refresh access time and increment count."""
        self.access_count += 1


# =============================================================================
# CONVERSATIONAL SEMANTIC CACHE
# =============================================================================

class ConversationalSemanticCache:
    """
    Multi-level semantic cache with session awareness.

    Lookup Strategy:
    1. Level 1: Session exact match (hash-based, O(1), instant)
    2. Level 2: Session semantic similarity (threshold=0.85, fast)
    3. Level 3: Global semantic similarity (threshold=0.92, strict)

    Session Management:
    - Each session has isolated cache namespace
    - Session invalidation on delta updates
    - Automatic cleanup of expired sessions
    """

    def __init__(
        self,
        embeddings: Embeddings,
        session_threshold: float = 0.85,
        global_threshold: float = 0.92,
        session_ttl: int = 3600,  # 1 hour
        global_ttl: int = 7200,   # 2 hours
        max_session_size: int = 100,
        max_global_size: int = 1000
    ):
        """
        Initialize conversational cache.

        Args:
            embeddings: LangChain embeddings model
            session_threshold: Similarity threshold for session cache (more lenient)
            global_threshold: Similarity threshold for global cache (stricter)
            session_ttl: Session cache TTL in seconds
            global_ttl: Global cache TTL in seconds
            max_session_size: Max entries per session
            max_global_size: Max entries in global cache
        """
        self.embeddings = embeddings
        self.session_threshold = session_threshold
        self.global_threshold = global_threshold
        self.session_ttl = session_ttl
        self.global_ttl = global_ttl
        self.max_session_size = max_session_size

        # Session caches: session_id -> {query_hash -> SessionCacheEntry}
        self.session_caches: Dict[str, Dict[str, SessionCacheEntry]] = {}
        self.session_access_times: Dict[str, float] = {}

        # Global semantic cache
        self.global_cache = SemanticCache(
            embeddings=embeddings,
            threshold=global_threshold,
            ttl=global_ttl,
            max_size=max_global_size
        )

        # Statistics
        self.stats = {
            "session_exact_hits": 0,
            "session_semantic_hits": 0,
            "global_hits": 0,
            "misses": 0,
            "total_requests": 0,
            "invalidations": 0
        }

        self._lock = asyncio.Lock()

        logger.info(
            f"[CONV_CACHE] Initialized (session_threshold={session_threshold}, "
            f"global_threshold={global_threshold})"
        )

    async def get_or_compute(
        self,
        query: str,
        session_id: Optional[str],
        compute_fn: Callable[[], Any],
        cache_type: str = "default"
    ) -> Tuple[Any, str]:
        """
        Get cached result or compute with multi-level lookup.

        Args:
            query: Query string to check
            session_id: Session identifier for session-aware caching
            compute_fn: Async function to compute result if cache miss
            cache_type: Type of cache (for statistics tracking)

        Returns:
            Tuple of (result, cache_level) where cache_level is:
            - "session_exact": Level 1 hit
            - "session_semantic": Level 2 hit
            - "global": Level 3 hit
            - "miss": Cache miss
        """
        async with self._lock:
            self.stats["total_requests"] += 1

        # Skip session caching if no session_id
        if not session_id:
            result = await self.global_cache.get(query)
            if result is not None:
                async with self._lock:
                    self.stats["global_hits"] += 1
                logger.info(f"[CONV_CACHE] Global hit (no session): {query[:50]}...")
                return (result, "global")

            # Compute and store in global cache only
            result = await compute_fn()

            # Don't cache empty/invalid results
            if result and (not isinstance(result, str) or result.strip()):
                await self._store_global(query, result)
                logger.debug(f"[CONV_CACHE] Stored global result (no session): {query[:50]}...")
            else:
                logger.warning(f"[CONV_CACHE] Skipping global cache for empty result: {query[:50]}...")

            async with self._lock:
                self.stats["misses"] += 1
            return (result, "miss")

        # Level 1: Session exact match
        query_hash = self._hash_query(query)
        session_cache = self.session_caches.get(session_id, {})

        if query_hash in session_cache:
            entry = session_cache[query_hash]
            if not entry.is_expired():
                entry.refresh()
                self.session_access_times[session_id] = time.time()
                async with self._lock:
                    self.stats["session_exact_hits"] += 1
                logger.info(f"[CONV_CACHE] ⚡ Level 1 hit (session exact): {query[:50]}...")
                return (entry.result, "session_exact")
            else:
                # Expired, remove
                del session_cache[query_hash]

        # Level 2: Session semantic match
        query_embedding = await self._embed_query(query)
        session_match = self._find_session_semantic_match(
            session_id, query_embedding, self.session_threshold
        )

        if session_match:
            session_match.refresh()
            self.session_access_times[session_id] = time.time()
            async with self._lock:
                self.stats["session_semantic_hits"] += 1
            logger.info(
                f"[CONV_CACHE] ⚡ Level 2 hit (session semantic): {query[:50]}... "
                f"(matched: {session_match.query[:30]}...)"
            )
            return (session_match.result, "session_semantic")

        # Level 3: Global semantic match
        global_result = await self.global_cache.get(query)
        if global_result is not None:
            # Store in session cache for future fast access
            await self._store_session(session_id, query, query_hash, query_embedding, global_result)
            async with self._lock:
                self.stats["global_hits"] += 1
            logger.info(f"[CONV_CACHE] Level 3 hit (global): {query[:50]}...")
            return (global_result, "global")

        # Cache miss - compute result
        async with self._lock:
            self.stats["misses"] += 1
        logger.info(f"[CONV_CACHE] Miss for: {query[:50]}... (computing)")

        result = await compute_fn()

        # Don't cache empty/invalid results
        if result and (not isinstance(result, str) or result.strip()):
            # Store in both session and global caches
            await self._store_multi_level(session_id, query, query_hash, query_embedding, result)
            logger.debug(f"[CONV_CACHE] Stored result for: {query[:50]}...")
        else:
            logger.warning(f"[CONV_CACHE] Skipping cache for empty result: {query[:50]}...")

        return (result, "miss")

    async def invalidate_session(
        self,
        session_id: str,
        reason: str = "delta_update"
    ):
        """
        Invalidate entire session cache.

        Args:
            session_id: Session to invalidate
            reason: Reason for invalidation (for logging)
        """
        async with self._lock:
            if session_id in self.session_caches:
                count = len(self.session_caches[session_id])
                del self.session_caches[session_id]
                if session_id in self.session_access_times:
                    del self.session_access_times[session_id]
                self.stats["invalidations"] += 1
                logger.info(
                    f"[CONV_CACHE] Invalidated session {session_id} "
                    f"({count} entries removed, reason: {reason})"
                )
            else:
                logger.debug(f"[CONV_CACHE] No cache to invalidate for session {session_id}")

    async def invalidate_global(self):
        """Invalidate entire global cache."""
        self.global_cache.invalidate()
        async with self._lock:
            self.stats["invalidations"] += 1
        logger.info("[CONV_CACHE] Invalidated global cache")

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        total = self.stats["total_requests"]
        total_hits = (
            self.stats["session_exact_hits"] +
            self.stats["session_semantic_hits"] +
            self.stats["global_hits"]
        )
        hit_rate = total_hits / total if total > 0 else 0.0

        global_stats = self.global_cache.get_stats()

        return {
            "total_requests": total,
            "total_hits": total_hits,
            "hit_rate": hit_rate,
            "session_exact_hits": self.stats["session_exact_hits"],
            "session_semantic_hits": self.stats["session_semantic_hits"],
            "global_hits": self.stats["global_hits"],
            "misses": self.stats["misses"],
            "invalidations": self.stats["invalidations"],
            "active_sessions": len(self.session_caches),
            "total_session_entries": sum(len(cache) for cache in self.session_caches.values()),
            "global_cache": {
                "size": global_stats["cache_size"],
                "hits": global_stats["hits"],
                "misses": global_stats["misses"],
                "hit_rate": global_stats["hit_rate"]
            }
        }

    async def cleanup_expired_sessions(self):
        """Remove expired sessions (background cleanup)."""
        async with self._lock:
            current_time = time.time()
            expired_sessions = []

            for session_id, last_access in self.session_access_times.items():
                if current_time - last_access > self.session_ttl:
                    expired_sessions.append(session_id)

            for session_id in expired_sessions:
                count = len(self.session_caches.get(session_id, {}))
                if session_id in self.session_caches:
                    del self.session_caches[session_id]
                if session_id in self.session_access_times:
                    del self.session_access_times[session_id]

                logger.info(
                    f"[CONV_CACHE] Cleaned up expired session {session_id} ({count} entries)"
                )

    # -------------------------------------------------------------------------
    # INTERNAL METHODS
    # -------------------------------------------------------------------------

    def _hash_query(self, query: str) -> str:
        """Generate hash for exact matching."""
        return hashlib.sha256(query.encode()).hexdigest()

    async def _embed_query(self, query: str) -> np.ndarray:
        """Embed query using embeddings model."""
        try:
            embedding = await self.embeddings.aembed_query(query)
            return np.array(embedding)
        except Exception as e:
            logger.error(f"[CONV_CACHE] Embedding error: {e}")
            # Fallback: use hash as pseudo-embedding
            hash_val = int(hashlib.sha256(query.encode()).hexdigest(), 16)
            return np.array([hash_val % 1000 / 1000.0])

    def _find_session_semantic_match(
        self,
        session_id: str,
        query_embedding: np.ndarray,
        threshold: float
    ) -> Optional[SessionCacheEntry]:
        """
        Find semantically similar entry in session cache.

        Args:
            session_id: Session to search in
            query_embedding: Query embedding vector
            threshold: Similarity threshold

        Returns:
            Matching SessionCacheEntry or None
        """
        session_cache = self.session_caches.get(session_id, {})
        best_similarity = 0.0
        best_entry = None

        for entry in session_cache.values():
            if entry.is_expired():
                continue

            similarity = self._cosine_similarity(query_embedding, entry.embedding)

            if similarity > best_similarity:
                best_similarity = similarity
                best_entry = entry

        if best_similarity >= threshold:
            logger.debug(
                f"[CONV_CACHE] Session similarity: {best_similarity:.3f} >= {threshold}"
            )
            return best_entry

        return None

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        try:
            dot_product = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)

            if norm_a == 0 or norm_b == 0:
                return 0.0

            return dot_product / (norm_a * norm_b)
        except Exception as e:
            logger.error(f"[CONV_CACHE] Similarity computation error: {e}")
            return 0.0

    async def _store_session(
        self,
        session_id: str,
        query: str,
        query_hash: str,
        embedding: np.ndarray,
        result: Any
    ):
        """Store result in session cache."""
        async with self._lock:
            if session_id not in self.session_caches:
                self.session_caches[session_id] = {}

            session_cache = self.session_caches[session_id]

            # Check size limit
            if len(session_cache) >= self.max_session_size:
                self._evict_session_lru(session_id)

            # Store entry
            entry = SessionCacheEntry(
                query=query,
                query_hash=query_hash,
                embedding=embedding,
                result=result,
                timestamp=time.time(),
                ttl=self.session_ttl
            )

            session_cache[query_hash] = entry
            self.session_access_times[session_id] = time.time()

            logger.debug(f"[CONV_CACHE] Stored in session {session_id}: {query[:50]}...")

    async def _store_global(self, query: str, result: Any):
        """Store result in global cache."""
        # Use existing SemanticCache logic
        await self.global_cache.get_or_compute(
            query=query,
            compute_fn=lambda: result  # Already computed
        )

    async def _store_multi_level(
        self,
        session_id: str,
        query: str,
        query_hash: str,
        embedding: np.ndarray,
        result: Any
    ):
        """Store result in both session and global caches."""
        # Session cache
        await self._store_session(session_id, query, query_hash, embedding, result)

        # Global cache (async, non-blocking)
        try:
            # Direct storage in global cache
            cache_key = self.global_cache._build_key(query, None)
            self.global_cache._store(cache_key, query, embedding, result)
        except Exception as e:
            logger.warning(f"[CONV_CACHE] Failed to store in global cache: {e}")

    def _evict_session_lru(self, session_id: str):
        """Evict least recently used entry from session cache."""
        session_cache = self.session_caches.get(session_id, {})
        if not session_cache:
            return

        # Find LRU entry (lowest access_count)
        lru_hash = min(session_cache.keys(), key=lambda h: session_cache[h].access_count)
        del session_cache[lru_hash]

        logger.debug(f"[CONV_CACHE] Evicted LRU entry from session {session_id}")


# =============================================================================
# SINGLETON ACCESSOR
# =============================================================================

_global_conversational_cache: Optional[ConversationalSemanticCache] = None


def set_conversational_cache(cache: ConversationalSemanticCache):
    """Set global conversational cache instance."""
    global _global_conversational_cache
    _global_conversational_cache = cache


def get_conversational_cache() -> Optional[ConversationalSemanticCache]:
    """Get global conversational cache instance."""
    return _global_conversational_cache
