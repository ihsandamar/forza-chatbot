"""
Semantic Cache for LLM Calls

Embedding-based caching to reduce redundant LLM calls for similar queries.

Features:
- Semantic similarity matching (cosine similarity)
- Configurable threshold (default: 0.95)
- TTL support for cache expiration
- Cache invalidation
- get_or_compute pattern

Usage:
    cache = SemanticCache(embeddings_model, threshold=0.95, ttl=3600)
    result = await cache.get_or_compute(
        query="user message",
        compute_fn=lambda: llm.ainvoke(prompt)
    )
"""

import logging
import hashlib
import time
from typing import Any, Callable, Dict, Optional, List, Tuple
from datetime import datetime, timedelta
import asyncio

import numpy as np
from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)


# =============================================================================
# CACHE ENTRY
# =============================================================================

class CacheEntry:
    """Single cache entry with embedding and metadata."""

    def __init__(
        self,
        query: str,
        embedding: List[float],
        result: Any,
        timestamp: float,
        ttl: Optional[int] = None
    ):
        self.query = query
        self.embedding = np.array(embedding)
        self.result = result
        self.timestamp = timestamp
        self.ttl = ttl

    def is_expired(self) -> bool:
        """Check if entry is expired based on TTL."""
        if self.ttl is None:
            return False
        return time.time() - self.timestamp > self.ttl

    def __repr__(self):
        return f"CacheEntry(query='{self.query[:50]}...', age={time.time() - self.timestamp:.1f}s)"


# =============================================================================
# SEMANTIC CACHE
# =============================================================================

class SemanticCache:
    """
    Embedding-based semantic cache for LLM results.

    Stores query embeddings and checks similarity for cache hits.
    Reduces redundant LLM calls for semantically similar queries.
    """

    def __init__(
        self,
        embeddings: Embeddings,
        threshold: float = 0.95,
        ttl: Optional[int] = 3600,  # 1 hour default
        max_size: int = 1000
    ):
        """
        Initialize semantic cache.

        Args:
            embeddings: LangChain embeddings model
            threshold: Similarity threshold for cache hit (0.0-1.0)
            ttl: Time-to-live in seconds (None = no expiration)
            max_size: Maximum cache size (LRU eviction)
        """
        self.embeddings = embeddings
        self.threshold = threshold
        self.ttl = ttl
        self.max_size = max_size

        self._cache: Dict[str, CacheEntry] = {}
        self._access_times: Dict[str, float] = {}

        self._hits = 0
        self._misses = 0

        logger.info(f"[CACHE] Initialized semantic cache (threshold={threshold}, ttl={ttl}s)")

    async def get_or_compute(
        self,
        query: str,
        compute_fn: Callable[[], Any],
        context: Optional[str] = None
    ) -> Any:
        """
        Get cached result or compute new one.

        Args:
            query: Query string to check
            compute_fn: Async function to compute result if cache miss
            context: Optional context to include in cache key

        Returns:
            Cached or computed result
        """
        # Build cache key
        cache_key = self._build_key(query, context)

        # Check exact match first (fast path)
        if cache_key in self._cache:
            entry = self._cache[cache_key]
            if not entry.is_expired():
                self._hits += 1
                self._access_times[cache_key] = time.time()
                logger.info(f"[CACHE] Exact hit for: {query[:50]}...")
                return entry.result
            else:
                # Expired, remove
                logger.info(f"[CACHE] Expired entry removed: {query[:50]}...")
                del self._cache[cache_key]
                del self._access_times[cache_key]

        # Compute embedding
        query_embedding = await self._embed_query(query)

        # Check semantic similarity (slow path)
        similar_entry = self._find_similar(query_embedding)

        if similar_entry:
            self._hits += 1
            logger.info(f"[CACHE] Semantic hit for: {query[:50]}...")
            logger.debug(f"[CACHE] Matched with: {similar_entry.query[:50]}...")
            return similar_entry.result

        # Cache miss - compute result
        self._misses += 1
        logger.info(f"[CACHE] Miss for: {query[:50]}... (computing)")

        result = await compute_fn()

        # Don't cache empty/invalid results
        if result and (not isinstance(result, str) or result.strip()):
            # Store in cache
            self._store(cache_key, query, query_embedding, result)
            logger.debug(f"[CACHE] Stored result for: {query[:50]}...")
        else:
            logger.warning(f"[CACHE] Skipping cache for empty result: {query[:50]}...")

        return result

    async def get(self, query: str, context: Optional[str] = None) -> Optional[Any]:
        """
        Get cached result without computing.

        Args:
            query: Query string to check
            context: Optional context

        Returns:
            Cached result or None if not found
        """
        cache_key = self._build_key(query, context)

        # Exact match
        if cache_key in self._cache:
            entry = self._cache[cache_key]
            if not entry.is_expired():
                self._hits += 1
                self._access_times[cache_key] = time.time()
                return entry.result
            else:
                del self._cache[cache_key]
                del self._access_times[cache_key]

        # Semantic match
        query_embedding = await self._embed_query(query)
        similar_entry = self._find_similar(query_embedding)

        if similar_entry:
            self._hits += 1
            return similar_entry.result

        self._misses += 1
        return None

    def invalidate(self, query: Optional[str] = None, context: Optional[str] = None):
        """
        Invalidate cache entry or entire cache.

        Args:
            query: Query to invalidate (None = invalidate all)
            context: Optional context
        """
        if query is None:
            # Clear all
            count = len(self._cache)
            self._cache.clear()
            self._access_times.clear()
            logger.info(f"[CACHE] Invalidated all entries ({count} removed)")
        else:
            # Clear specific
            cache_key = self._build_key(query, context)
            if cache_key in self._cache:
                del self._cache[cache_key]
                del self._access_times[cache_key]
                logger.info(f"[CACHE] Invalidated: {query[:50]}...")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate": hit_rate,
            "cache_size": len(self._cache),
            "max_size": self.max_size
        }

    # -------------------------------------------------------------------------
    # INTERNAL METHODS
    # -------------------------------------------------------------------------

    def _build_key(self, query: str, context: Optional[str]) -> str:
        """Build cache key from query and context."""
        if context:
            combined = f"{query}::{context}"
        else:
            combined = query

        # Hash to fixed-length key
        return hashlib.sha256(combined.encode()).hexdigest()

    async def _embed_query(self, query: str) -> np.ndarray:
        """Embed query using embeddings model."""
        try:
            embedding = await self.embeddings.aembed_query(query)
            return np.array(embedding)
        except Exception as e:
            logger.error(f"[CACHE] Embedding error: {e}")
            # Fallback: use hash as pseudo-embedding (no semantic matching)
            hash_val = int(hashlib.sha256(query.encode()).hexdigest(), 16)
            return np.array([hash_val % 1000 / 1000.0])

    def _find_similar(self, query_embedding: np.ndarray) -> Optional[CacheEntry]:
        """
        Find semantically similar cached entry.

        Args:
            query_embedding: Query embedding vector

        Returns:
            Similar CacheEntry or None
        """
        best_similarity = 0.0
        best_entry = None

        for entry in self._cache.values():
            if entry.is_expired():
                continue

            similarity = self._cosine_similarity(query_embedding, entry.embedding)

            if similarity > best_similarity:
                best_similarity = similarity
                best_entry = entry

        if best_similarity >= self.threshold:
            logger.debug(f"[CACHE] Similarity: {best_similarity:.3f} >= {self.threshold}")
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
            logger.error(f"[CACHE] Similarity computation error: {e}")
            return 0.0

    def _store(
        self,
        cache_key: str,
        query: str,
        embedding: np.ndarray,
        result: Any
    ):
        """Store result in cache with LRU eviction."""
        # Check size limit
        if len(self._cache) >= self.max_size:
            self._evict_lru()

        # Store entry
        entry = CacheEntry(
            query=query,
            embedding=embedding,
            result=result,
            timestamp=time.time(),
            ttl=self.ttl
        )

        self._cache[cache_key] = entry
        self._access_times[cache_key] = time.time()

        logger.debug(f"[CACHE] Stored: {query[:50]}...")

    def _evict_lru(self):
        """Evict least recently used entry."""
        if not self._access_times:
            return

        # Find LRU entry
        lru_key = min(self._access_times.keys(), key=lambda k: self._access_times[k])

        # Remove
        del self._cache[lru_key]
        del self._access_times[lru_key]

        logger.debug(f"[CACHE] Evicted LRU entry")


# =============================================================================
# CACHE DECORATOR
# =============================================================================

def with_semantic_cache(cache: Optional[SemanticCache], context_fn: Optional[Callable] = None):
    """
    Decorator to add semantic caching to async functions.

    Usage:
        @with_semantic_cache(cache, context_fn=lambda args: args['state'])
        async def my_llm_function(query: str, state: dict):
            return await llm.ainvoke(query)

    Args:
        cache: SemanticCache instance (None = no caching)
        context_fn: Function to extract context from function args
    """
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            if cache is None:
                # No caching
                return await func(*args, **kwargs)

            # Extract query (assume first arg is query)
            query = args[0] if args else kwargs.get('query', '')

            # Extract context if context_fn provided
            context = None
            if context_fn:
                try:
                    context = context_fn({'args': args, 'kwargs': kwargs})
                except Exception as e:
                    logger.warning(f"[CACHE] Context extraction failed: {e}")

            # Use cache
            return await cache.get_or_compute(
                query=query,
                compute_fn=lambda: func(*args, **kwargs),
                context=str(context) if context else None
            )

        return wrapper
    return decorator
