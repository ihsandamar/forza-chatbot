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


def test_business_rules_store_rebuilds_when_default_collection_empty():
    """initialize() must call _build_index() when default_rules_collection is empty even if rules_collection is not."""
    # Create instance without going through __init__ to avoid import issues
    from src.graphs.report_agent.subagents.text2sql.stores.business_rules_store import BusinessRulesStore

    store = BusinessRulesStore.__new__(BusinessRulesStore)
    store._client = MagicMock()
    store._embedding_fn = MagicMock()
    store.rules_file_path = MagicMock()
    store.rules_data = {"business_logic_rules": []}

    mock_rules_col = MagicMock()
    mock_rules_col.count.return_value = 5  # rules_collection has data
    mock_default_col = MagicMock()
    mock_default_col.count.return_value = 0  # default_rules_collection is EMPTY

    store._client.get_or_create_collection.side_effect = [mock_rules_col, mock_default_col]
    store._build_index = MagicMock()

    store.initialize()

    store._build_index.assert_called_once()


def test_business_rules_store_search_rules_raises_if_not_initialized():
    """search_rules() must raise RuntimeError (not AttributeError) if called before initialize()."""
    from src.graphs.report_agent.subagents.text2sql.stores.business_rules_store import BusinessRulesStore

    store = BusinessRulesStore.__new__(BusinessRulesStore)
    store.rules_collection = None
    store.default_rules_collection = None

    with pytest.raises(RuntimeError, match="initialize"):
        store.search_rules("test query")
