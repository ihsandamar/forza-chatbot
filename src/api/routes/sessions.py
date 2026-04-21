"""
Session Management API Endpoints

Phase 4: API endpoints for explicit session management.

Features:
- Explicit session end with immediate table cleanup
- Session status and metadata retrieval
- Integration with TableRegistry for resource management

Endpoints:
- POST /sessions/{session_id}/end: End session and cleanup resources
- GET /sessions/{session_id}/status: Get session status and table info
"""

import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException

from src.graphs.report_agent.table_registry import get_table_registry
import pyodbc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# =============================================================================
# SESSION ENDPOINTS
# =============================================================================

@router.post("/{session_id}/end")
async def end_session(session_id: str) -> Dict[str, Any]:
    """
    Explicitly end session and cleanup resources immediately.

    This endpoint:
    1. Drops the master table for the session
    2. Unregisters table from registry
    3. Invalidates session cache

    Args:
        session_id: Session identifier

    Returns:
        Cleanup status with table name if cleaned up
    """
    logger.info(f"[SESSION_API] Ending session: {session_id}")

    try:
        registry = get_table_registry()
        metadata = registry.tables.get(session_id)

        if not metadata:
            logger.info(f"[SESSION_API] No active table for session {session_id}")
            return {
                "status": "no_table",
                "session_id": session_id,
                "message": "No active table found for this session"
            }

        # Get DB connection string from environment
        import os
        db_connection_string = os.getenv("DATABASE_URL")
        if not db_connection_string:
            raise HTTPException(
                status_code=500,
                detail="DATABASE_URL not configured"
            )

        # Drop table
        table_name = metadata.table_name
        drop_sql = f"DROP TABLE IF EXISTS {table_name};"

        try:
            conn_str = db_connection_string
            if conn_str.startswith("mssql+pyodbc://"):
                conn_str = conn_str.replace("mssql+pyodbc://", "")
            conn = pyodbc.connect(conn_str, autocommit=True, timeout=30)
            conn.execute(drop_sql)
            conn.close()
            logger.info(f"[SESSION_API] Dropped table {table_name}")
        except Exception as e:
            logger.error(f"[SESSION_API] Failed to drop table {table_name}: {e}")

        # Unregister from registry
        unregistered = await registry.unregister_table(session_id)

        logger.info(
            f"[SESSION_API] Session {session_id} ended successfully "
            f"(table={table_name}, queries={metadata.query_count})"
        )

        return {
            "status": "success",
            "session_id": session_id,
            "table_cleaned": table_name,
            "query_count": metadata.query_count,
            "session_age_seconds": metadata.age_seconds()
        }

    except Exception as e:
        logger.error(f"[SESSION_API] Error ending session {session_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to end session: {str(e)}"
        )


@router.get("/{session_id}/status")
async def get_session_status(session_id: str) -> Dict[str, Any]:
    """
    Get session status and table information.

    Args:
        session_id: Session identifier

    Returns:
        Session status with table metadata
    """
    logger.info(f"[SESSION_API] Getting status for session: {session_id}")

    try:
        registry = get_table_registry()
        metadata = registry.tables.get(session_id)

        if not metadata:
            return {
                "status": "no_table",
                "session_id": session_id,
                "active": False
            }

        is_expired = metadata.is_expired()

        return {
            "status": "expired" if is_expired else "active",
            "session_id": session_id,
            "active": not is_expired,
            "table_name": metadata.table_name,
            "created_at": metadata.created_at,
            "last_accessed_at": metadata.last_accessed_at,
            "age_seconds": metadata.age_seconds(),
            "ttl_remaining_seconds": metadata.ttl_remaining(),
            "query_count": metadata.query_count,
            "document_count": metadata.document_count
        }

    except Exception as e:
        logger.error(f"[SESSION_API] Error getting session status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get session status: {str(e)}"
        )


@router.get("/active")
async def get_active_sessions() -> Dict[str, Any]:
    """
    Get list of all active sessions.

    Returns:
        List of active sessions with metadata
    """
    logger.info("[SESSION_API] Getting all active sessions")

    try:
        registry = get_table_registry()
        all_tables = await registry.get_all_tables()

        active_sessions = []
        expired_sessions = []

        for metadata in all_tables:
            session_info = {
                "session_id": metadata.session_id,
                "table_name": metadata.table_name,
                "age_seconds": metadata.age_seconds(),
                "ttl_remaining_seconds": metadata.ttl_remaining(),
                "query_count": metadata.query_count,
                "document_count": metadata.document_count
            }

            if metadata.is_expired():
                expired_sessions.append(session_info)
            else:
                active_sessions.append(session_info)

        return {
            "total_sessions": len(all_tables),
            "active_count": len(active_sessions),
            "expired_count": len(expired_sessions),
            "active_sessions": active_sessions,
            "expired_sessions": expired_sessions
        }

    except Exception as e:
        logger.error(f"[SESSION_API] Error getting active sessions: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get active sessions: {str(e)}"
        )
