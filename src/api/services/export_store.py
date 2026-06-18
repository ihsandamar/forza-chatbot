"""Export store service.

Stores export buffers in memory keyed by session_id so the
/api/export/{session_id} endpoint can serve them.
"""
from io import BytesIO
from typing import Dict, Optional, Tuple

_store: Dict[str, Tuple[BytesIO, str, str]] = {}


def put(session_id: str, buffer: BytesIO, filename: str, content_type: str) -> None:
    """Persist an export buffer for the given session (overwrites existing)."""
    _store[session_id] = (buffer, filename, content_type)


def get(session_id: str) -> Optional[Tuple[BytesIO, str, str]]:
    """Retrieve a stored export buffer.  Returns None if not found."""
    return _store.get(session_id)


def delete(session_id: str) -> None:
    """Remove a stored export buffer."""
    _store.pop(session_id, None)
