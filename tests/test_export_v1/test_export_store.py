import pytest
from io import BytesIO
from src.api.services import export_store


def setup_function():
    export_store._store.clear()


def test_put_and_get():
    buf = BytesIO(b"hello")
    export_store.put("sess-1", buf, "rapor.csv", "text/csv")
    result = export_store.get("sess-1")
    assert result is not None
    buffer, filename, content_type = result
    buffer.seek(0)
    assert buffer.read() == b"hello"
    assert filename == "rapor.csv"
    assert content_type == "text/csv"


def test_overwrite_on_second_put():
    export_store.put("sess-2", BytesIO(b"first"), "r1.csv", "text/csv")
    export_store.put("sess-2", BytesIO(b"second"), "r2.csv", "text/csv")
    result = export_store.get("sess-2")
    assert result is not None
    buf, fname, _ = result
    buf.seek(0)
    assert buf.read() == b"second"
    assert fname == "r2.csv"


def test_get_missing_returns_none():
    assert export_store.get("nonexistent-session-xyz") is None


def test_delete_removes_entry():
    export_store.put("sess-3", BytesIO(b"x"), "r.csv", "text/csv")
    export_store.delete("sess-3")
    assert export_store.get("sess-3") is None
