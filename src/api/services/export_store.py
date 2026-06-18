"""Export store service — stub for Task 11.

Stores export buffers in memory keyed by session_id so the
/api/export/{session_id} endpoint can serve them.  Full
implementation will be wired in Task 11.
"""
from io import BytesIO
from typing import Dict, Tuple

_store: Dict[str, Tuple[BytesIO, str, str]] = {}


def put(session_id: str, buffer: BytesIO, filename: str, content_type: str) -> None:
    """Persist an export buffer for the given session."""
    buffer.seek(0)
    _store[session_id] = (buffer, filename, content_type)


def get(session_id: str) -> Tuple[BytesIO, str, str]:
    """Retrieve a stored export buffer.  Raises KeyError if not found."""
    return _store[session_id]


def clear(session_id: str) -> None:
    """Remove a stored export buffer."""
    _store.pop(session_id, None)
