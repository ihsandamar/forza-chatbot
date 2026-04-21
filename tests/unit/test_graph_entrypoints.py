from unittest.mock import patch, MagicMock


def test_make_graph_passes_base_url_to_llm():
    mock_config = MagicMock()
    mock_config.llm.provider = "openai"
    mock_config.llm.model = "gpt-4"
    mock_config.llm.temperature = 0
    mock_config.llm.api_key = "sk-test"
    mock_config.llm.base_url = "https://custom.api.com/v1"

    captured = {}

    import src.graphs.graph_entrypoints as ge
    ge._config_cache = None

    with patch("src.graphs.graph_entrypoints.ConfigLoader.load_config", return_value=mock_config), \
         patch("src.graphs.graph_entrypoints.LLM", side_effect=lambda **kw: captured.update(kw) or MagicMock()) as mock_llm, \
         patch("src.graphs.graph_entrypoints.GraphRepository"):
        ge._make_graph("supervisor")

    assert captured.get("base_url") == "https://custom.api.com/v1"


def test_llm_get_chat_openai_passes_base_url():
    from src.models.llm import LLM
    with patch("src.models.llm.ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm = LLM(provider="openai", model="gpt-4", api_key="sk-test", base_url="https://custom.api.com/v1")
        llm.get_chat()
    call_kwargs = mock_openai.call_args[1]
    assert call_kwargs.get("base_url") == "https://custom.api.com/v1"


def test_llm_get_chat_openai_none_base_url_passes_none():
    from src.models.llm import LLM
    with patch("src.models.llm.ChatOpenAI") as mock_openai:
        mock_openai.return_value = MagicMock()
        llm = LLM(provider="openai", model="gpt-4", api_key="sk-test", base_url=None)
        llm.get_chat()
    call_kwargs = mock_openai.call_args[1]
    assert "base_url" in call_kwargs  # must be passed, even if None
