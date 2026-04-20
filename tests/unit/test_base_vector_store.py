from unittest.mock import MagicMock, patch
import pytest


def _make_store(embedding_fn=None):
    with patch("src.graphs.report_agent.subagents.text2sql.stores.base.chromadb"):
        from src.graphs.report_agent.subagents.text2sql.stores.base import BaseVectorStore

        class Impl(BaseVectorStore):
            def __init__(self):
                super().__init__(embedding_fn or MagicMock())
                self.init_calls = []

            def initialize(self, force_recreate: bool = False) -> None:
                self.init_calls.append(force_recreate)

        return Impl()


def test_rebuild_calls_initialize_with_force_recreate_true():
    store = _make_store()
    store.rebuild()
    assert store.init_calls == [True]


def test_embedding_fn_stored_on_instance():
    mock_fn = MagicMock()
    store = _make_store(mock_fn)
    assert store._embedding_fn is mock_fn


def test_client_created_on_init():
    with patch("src.graphs.report_agent.subagents.text2sql.stores.base.chromadb") as mock_chroma:
        from src.graphs.report_agent.subagents.text2sql.stores.base import BaseVectorStore

        class Impl(BaseVectorStore):
            def initialize(self, force_recreate=False):
                pass

        Impl(MagicMock())
        mock_chroma.EphemeralClient.assert_called_once()
