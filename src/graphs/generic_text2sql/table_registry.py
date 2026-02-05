"""
Table Registry for Master Table Lifecycle Management

Phase 4 enhancement: Session-aware table management with TTL and automatic cleanup.

Features:
- Session-based table naming (MasterReportDocumentTable_{session_id})
- 15-minute TTL with automatic refresh on access
- Background cleanup of expired tables
- Thread-safe operations with asyncio locks
- Query count tracking for metrics

Expected Behavior:
- Tables persist across queries in same session
- Automatic cleanup after 15 minutes of inactivity
- Explicit cleanup via session end endpoint
- No resource leaks
"""

import logging
import time
import asyncio
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


# =============================================================================
# TABLE METADATA
# =============================================================================

@dataclass
class TableMetadata:
    """Metadata for a managed master table."""
    table_name: str
    session_id: str
    created_at: float
    last_accessed_at: float
    ttl_seconds: int = 900  # 15 minutes default
    query_count: int = 0
    document_count: int = 0

    def is_expired(self) -> bool:
        """Check if table TTL has expired."""
        return time.time() - self.last_accessed_at > self.ttl_seconds

    def refresh_ttl(self):
        """Refresh access time and increment query count."""
        self.last_accessed_at = time.time()
        self.query_count += 1

    def ttl_remaining(self) -> float:
        """Get remaining TTL in seconds."""
        elapsed = time.time() - self.last_accessed_at
        remaining = self.ttl_seconds - elapsed
        return max(0.0, remaining)

    def age_seconds(self) -> float:
        """Get age of table in seconds."""
        return time.time() - self.created_at

    def __repr__(self):
        return (
            f"TableMetadata(table={self.table_name}, session={self.session_id}, "
            f"age={self.age_seconds():.1f}s, ttl_remaining={self.ttl_remaining():.1f}s, "
            f"queries={self.query_count})"
        )


# =============================================================================
# TABLE REGISTRY
# =============================================================================

class TableRegistry:
    """
    Registry for managing master table lifecycle.

    Responsibilities:
    - Track active tables by session_id
    - Enforce TTL and cleanup expired tables
    - Provide thread-safe table access
    - Support background cleanup tasks
    """

    def __init__(self, default_ttl: int = 900):
        """
        Initialize table registry.

        Args:
            default_ttl: Default TTL in seconds (default: 900 = 15 minutes)
        """
        self.default_ttl = default_ttl
        self.tables: Dict[str, TableMetadata] = {}
        self.lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_running = False

        logger.info(f"[TABLE_REGISTRY] Initialized (default_ttl={default_ttl}s)")

    async def register_table(
        self,
        session_id: str,
        table_name: str,
        document_count: int = 0
    ) -> TableMetadata:
        """
        Register a new table or refresh existing table TTL.

        Args:
            session_id: Session identifier
            table_name: Name of the master table
            document_count: Number of documents in table

        Returns:
            TableMetadata for the registered table
        """
        async with self.lock:
            if session_id in self.tables:
                # Existing table - refresh TTL
                metadata = self.tables[session_id]
                metadata.refresh_ttl()
                if document_count > 0:
                    metadata.document_count = document_count
                logger.info(
                    f"[TABLE_REGISTRY] ⚡ Refreshed TTL for {table_name} "
                    f"(queries={metadata.query_count}, ttl={metadata.ttl_remaining():.0f}s)"
                )
            else:
                # New table - register
                metadata = TableMetadata(
                    table_name=table_name,
                    session_id=session_id,
                    created_at=time.time(),
                    last_accessed_at=time.time(),
                    ttl_seconds=self.default_ttl,
                    document_count=document_count
                )
                self.tables[session_id] = metadata
                logger.info(
                    f"[TABLE_REGISTRY] ✅ Registered {table_name} "
                    f"(session={session_id}, ttl={self.default_ttl}s)"
                )

            return metadata

    async def check_table_exists(self, session_id: str) -> Optional[TableMetadata]:
        """
        Check if table exists and is not expired.

        Args:
            session_id: Session identifier

        Returns:
            TableMetadata if exists and not expired, None otherwise
        """
        async with self.lock:
            metadata = self.tables.get(session_id)

            if metadata is None:
                logger.debug(f"[TABLE_REGISTRY] No table for session {session_id}")
                return None

            if metadata.is_expired():
                logger.info(
                    f"[TABLE_REGISTRY] Table {metadata.table_name} expired "
                    f"(age={metadata.age_seconds():.0f}s)"
                )
                return None

            # Refresh TTL on check
            metadata.refresh_ttl()
            logger.debug(
                f"[TABLE_REGISTRY] Table {metadata.table_name} exists "
                f"(ttl={metadata.ttl_remaining():.0f}s)"
            )
            return metadata

    async def unregister_table(self, session_id: str) -> Optional[str]:
        """
        Unregister table (called after DROP TABLE).

        Args:
            session_id: Session identifier

        Returns:
            Table name that was unregistered, or None
        """
        async with self.lock:
            metadata = self.tables.pop(session_id, None)
            if metadata:
                logger.info(
                    f"[TABLE_REGISTRY] Unregistered {metadata.table_name} "
                    f"(session={session_id}, age={metadata.age_seconds():.0f}s, "
                    f"queries={metadata.query_count})"
                )
                return metadata.table_name
            return None

    async def get_all_tables(self) -> List[TableMetadata]:
        """Get list of all registered tables."""
        async with self.lock:
            return list(self.tables.values())

    async def get_expired_tables(self) -> List[TableMetadata]:
        """Get list of expired tables."""
        async with self.lock:
            return [meta for meta in self.tables.values() if meta.is_expired()]

    async def cleanup_expired(
        self,
        db_connection_string: str,
        dry_run: bool = False
    ) -> List[str]:
        """
        Cleanup expired tables by dropping them from database.

        Args:
            db_connection_string: Database connection string
            dry_run: If True, only log what would be cleaned up

        Returns:
            List of table names that were cleaned up
        """
        expired = await self.get_expired_tables()

        if not expired:
            logger.debug("[TABLE_REGISTRY] No expired tables to cleanup")
            return []

        cleaned_tables = []

        for metadata in expired:
            session_id = metadata.session_id
            table_name = metadata.table_name

            if dry_run:
                logger.info(
                    f"[TABLE_REGISTRY] [DRY RUN] Would cleanup {table_name} "
                    f"(age={metadata.age_seconds():.0f}s, queries={metadata.query_count})"
                )
                cleaned_tables.append(table_name)
                continue

            try:
                # Drop table from database
                from src.graphs.generic_text2sql.sql_database_connection import execute_sql

                drop_sql = f"DROP TABLE IF EXISTS {table_name};"
                await execute_sql(
                    drop_sql,
                    db_connection_string,
                    return_direct=True
                )

                # Unregister from registry
                await self.unregister_table(session_id)

                cleaned_tables.append(table_name)
                logger.info(
                    f"[TABLE_REGISTRY] ✅ Cleaned up {table_name} "
                    f"(age={metadata.age_seconds():.0f}s, queries={metadata.query_count})"
                )

            except Exception as e:
                logger.error(f"[TABLE_REGISTRY] Failed to cleanup {table_name}: {e}")

        if cleaned_tables:
            logger.info(
                f"[TABLE_REGISTRY] Cleanup complete: {len(cleaned_tables)} tables removed"
            )

        return cleaned_tables

    def start_background_cleanup(
        self,
        db_connection_string: str,
        interval: int = 300  # 5 minutes
    ):
        """
        Start background task for periodic cleanup.

        Args:
            db_connection_string: Database connection string
            interval: Cleanup interval in seconds (default: 300 = 5 minutes)
        """
        if self._cleanup_running:
            logger.warning("[TABLE_REGISTRY] Background cleanup already running")
            return

        self._cleanup_running = True

        async def cleanup_loop():
            logger.info(
                f"[TABLE_REGISTRY] Started background cleanup (interval={interval}s)"
            )
            while self._cleanup_running:
                try:
                    await asyncio.sleep(interval)
                    await self.cleanup_expired(db_connection_string)
                except asyncio.CancelledError:
                    logger.info("[TABLE_REGISTRY] Background cleanup cancelled")
                    break
                except Exception as e:
                    logger.error(f"[TABLE_REGISTRY] Background cleanup error: {e}")

        self._cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info("[TABLE_REGISTRY] Background cleanup task started")

    def stop_background_cleanup(self):
        """Stop background cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_running = False
            self._cleanup_task.cancel()
            logger.info("[TABLE_REGISTRY] Stopped background cleanup task")

    def get_stats(self) -> Dict:
        """Get registry statistics."""
        tables = list(self.tables.values())
        if not tables:
            return {
                "total_tables": 0,
                "total_queries": 0,
                "avg_age_seconds": 0,
                "avg_ttl_remaining": 0
            }

        total_queries = sum(t.query_count for t in tables)
        avg_age = sum(t.age_seconds() for t in tables) / len(tables)
        avg_ttl = sum(t.ttl_remaining() for t in tables) / len(tables)

        return {
            "total_tables": len(tables),
            "total_queries": total_queries,
            "avg_age_seconds": avg_age,
            "avg_ttl_remaining": avg_ttl,
            "expired_count": sum(1 for t in tables if t.is_expired())
        }


# =============================================================================
# SINGLETON ACCESSOR
# =============================================================================

_global_table_registry: Optional[TableRegistry] = None


def get_table_registry() -> TableRegistry:
    """
    Get global table registry instance (singleton).

    Creates registry on first access.
    """
    global _global_table_registry
    if _global_table_registry is None:
        _global_table_registry = TableRegistry(default_ttl=900)
    return _global_table_registry


def set_table_registry(registry: TableRegistry):
    """Set global table registry instance (for testing)."""
    global _global_table_registry
    _global_table_registry = registry
