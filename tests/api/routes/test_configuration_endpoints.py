# tests/api/routes/test_configuration_endpoints.py
"""Tests for GET/POST /api/configuration using RuntimeAgentSettings."""
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.configuration import router
from src.api.dependencies import get_chat_service
from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.core.runtime_agent_settings import RuntimeAgentSettings, SubAgentSettings


def _make_client(runtime_agent_settings=None) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/configuration")

    mock_chatbot = MagicMock(spec=Chatbot)
    mock_chatbot.get_runtime_settings.return_value = runtime_agent_settings

    mock_service = MagicMock(spec=ChatService)
    mock_service.chatbot = mock_chatbot

    app.dependency_overrides[get_chat_service] = lambda: mock_service
    return TestClient(app)


class TestGetConfiguration:
    def test_returns_200_with_settings(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(system_prompt="route", token="secret-tok"),
            "chat": SubAgentSettings(system_prompt="chat"),
        })
        client = _make_client(settings)
        resp = client.get("/api/configuration")
        assert resp.status_code == 200
        data = resp.json()
        assert "subagents" in data
        assert "routing" in data["subagents"]
        assert data["subagents"]["routing"]["system_prompt"] == "route"
        assert data["subagents"]["routing"]["has_token"] is True
        assert data["subagents"]["routing"]["token_preview"] == "secret-tok"
        assert data["subagents"]["chat"]["has_token"] is False
        assert "available_subagent_types" in data
        assert "routing" in data["available_subagent_types"]

    def test_returns_200_with_empty_settings(self):
        client = _make_client(RuntimeAgentSettings())
        resp = client.get("/api/configuration")
        assert resp.status_code == 200
        data = resp.json()
        assert data["subagents"] == {}
        assert data["available_subagent_types"] == []

    def test_no_llm_field_in_response(self):
        client = _make_client(RuntimeAgentSettings())
        resp = client.get("/api/configuration")
        assert "llm" not in resp.json()

    def test_503_when_no_chatbot(self):
        app = FastAPI()
        app.include_router(router, prefix="/api/configuration")
        mock_service = MagicMock(spec=ChatService)
        mock_service.chatbot = None
        app.dependency_overrides[get_chat_service] = lambda: mock_service
        client = TestClient(app)
        resp = client.get("/api/configuration")
        assert resp.status_code == 503

    def test_token_preview_long_token(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="this-is-a-long-token-value")
        })
        client = _make_client(settings)
        data = client.get("/api/configuration").json()
        assert data["subagents"]["routing"]["token_preview"] == "this-is-a-..."
        assert data["subagents"]["routing"]["has_token"] is True

    def test_token_preview_short_token(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="short")
        })
        client = _make_client(settings)
        data = client.get("/api/configuration").json()
        assert data["subagents"]["routing"]["token_preview"] == "short"


class TestPostConfiguration:
    def test_returns_200_on_valid_update(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="old", system_prompt="old-prompt"),
        })
        client = _make_client(settings)
        resp = client.post("/api/configuration", json={
            "subagents": {"routing": {"token": "new-token"}}
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "routing token" in data["message"]

    def test_no_changes_message(self):
        settings = RuntimeAgentSettings(subagents={
            "routing": SubAgentSettings(token="tok"),
        })
        client = _make_client(settings)
        resp = client.post("/api/configuration", json={"subagents": {}})
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "No changes"
