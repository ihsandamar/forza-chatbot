# Launch Layer Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate FastAPI, Gradio, and CLI startup into `src/launch/` so every launch path is readable, has a single config load, and main.py shrinks to ~25 lines.

**Architecture:** A `src/core/app_config.py` singleton feeds all launchers. `src/launch/` holds one class per interface (ApiLauncher, GradioLauncher, CliLauncher) plus a `build_chat_service()` factory. `main.py` becomes a thin argparse wrapper; `api_app.py` stays as a thin PyInstaller entry point.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, LangGraph, Gradio, pytest, unittest.mock

---

## File Map

**Create:**
- `src/core/app_config.py` — `get_config()` singleton + `reset_config()`
- `src/launch/__init__.py` — `get_launcher(interface, config_path)` factory
- `src/launch/_chat_service.py` — `build_chat_service(config)` factory (replaces `di_container.py`)
- `src/launch/api_launcher.py` — `ApiLauncher` class
- `src/launch/gradio_launcher.py` — `GradioLauncher` class
- `src/launch/cli_launcher.py` — `CliLauncher` class
- `tests/test_app_config.py`
- `tests/test_launcher_factory.py`

**Modify:**
- `src/api/main.py` — remove module-level `app`; export `build_fastapi_app(config) -> FastAPI`
- `src/interfaces/cli_interface.py` — fix broken import + align method calls with canonical ChatService
- `main.py` — rewrite to ~25 lines using `get_launcher()`
- `api_app.py` — rewrite to ~15 lines (keep pysqlite3 patch + PyInstaller path setup)
- `src/__init__.py` — remove `di_container` export
- `langgraph.json` — remove stale graph entries

**Delete:**
- `src/api/chat_service.py` — canonical is `src/api/services/chat_service.py`
- `src/di_container.py` — logic moves to `src/launch/_chat_service.py`

---

### Task 1: Config Singleton — `src/core/app_config.py`

**Files:**
- Create: `src/core/app_config.py`
- Create: `tests/test_app_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app_config.py
import pytest
from unittest.mock import patch, MagicMock


def test_get_config_returns_same_instance():
    """get_config() is a singleton — two calls return the same object."""
    from src.core.app_config import get_config, reset_config
    reset_config()
    c1 = get_config()
    c2 = get_config()
    assert c1 is c2


def test_reset_config_clears_singleton():
    """reset_config() forces the next get_config() to reload."""
    from src.core.app_config import get_config, reset_config
    reset_config()
    c1 = get_config()
    reset_config()
    c2 = get_config()
    # After reset, a new object is created (identity differs)
    assert c1 is not c2


def test_get_config_loads_from_path():
    """get_config() delegates to ConfigLoader.load_config with correct path."""
    from src.core.app_config import get_config, reset_config
    reset_config()
    mock_config = MagicMock()
    with patch("src.core.app_config.ConfigLoader.load_config", return_value=mock_config) as mock_load:
        result = get_config("config/config.yaml")
        mock_load.assert_called_once_with("config/config.yaml")
        assert result is mock_config


def test_get_config_does_not_reload_on_second_call():
    """ConfigLoader is called only once even if get_config() is called many times."""
    from src.core.app_config import get_config, reset_config
    reset_config()
    mock_config = MagicMock()
    with patch("src.core.app_config.ConfigLoader.load_config", return_value=mock_config) as mock_load:
        get_config()
        get_config()
        get_config()
        assert mock_load.call_count == 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_app_config.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `src.core.app_config` does not exist yet.

- [ ] **Step 3: Create `src/core/app_config.py`**

```python
# src/core/app_config.py
from typing import Optional
from src.services.config_loader import ConfigLoader

_config = None


def get_config(path: str = "config/config.yaml"):
    """
    Return the application config singleton.
    Loads from `path` on first call; returns cached object thereafter.
    """
    global _config
    if _config is None:
        _config = ConfigLoader.load_config(path)
    return _config


def reset_config() -> None:
    """Clear the singleton — for test isolation only, not for production use."""
    global _config
    _config = None
```

- [ ] **Step 4: Run tests to confirm they pass**

```
pytest tests/test_app_config.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/core/app_config.py tests/test_app_config.py
git commit -m "feat: add get_config() singleton to src/core/app_config"
```

---

### Task 2: `build_chat_service()` Factory — `src/launch/_chat_service.py`

**Files:**
- Create: `src/launch/_chat_service.py`

> No unit test for this factory: it wires real LLM/graph/chatbot dependencies that require live credentials. Integration is verified in Task 8 (running `main.py --interface api`). A smoke test for the import is sufficient.

- [ ] **Step 1: Create `src/launch/` package placeholder**

```python
# src/launch/__init__.py
# populated in Task 7
```

- [ ] **Step 2: Create `src/launch/_chat_service.py`**

```python
# src/launch/_chat_service.py
"""
Unified ChatService factory — used by all launchers.

This replaces src/di_container.py.
Canonical ChatService: src/api/services/chat_service.py
"""
from src.core.app_config import get_config
from src.api.services.chat_service import ChatService
from src.core.chatbot import Chatbot
from src.models.llm import LLM
from src.graphs.graph_repository import GraphRepository


def build_chat_service(config=None) -> ChatService:
    """
    Build and return a fully wired ChatService.

    Args:
        config: Config object from get_config(). If None, get_config() is called.

    Returns:
        ChatService instance backed by the LLM and graph specified in config.
    """
    if config is None:
        config = get_config()

    llm = LLM(
        provider=config.llm.provider,
        model=config.llm.model,
        temperature=config.llm.temperature,
        api_key=config.llm.api_key,
        base_url=getattr(config.llm, "base_url", None),
    )
    graph = GraphRepository(llm).get(config.chatbot.graph_type)
    chatbot = Chatbot(llm=llm.get_chat(), graph=graph)
    return ChatService(chatbot=chatbot)
```

- [ ] **Step 3: Verify the module imports without error**

```
python -c "from src.launch._chat_service import build_chat_service; print('OK')"
```

Expected: `OK` (no import error).

- [ ] **Step 4: Commit**

```bash
git add src/launch/__init__.py src/launch/_chat_service.py
git commit -m "feat: add build_chat_service() factory to src/launch"
```

---

### Task 3: Refactor `src/api/main.py` → `build_fastapi_app(config)`

**Files:**
- Modify: `src/api/main.py`

The module-level `app = FastAPI(...)` is removed. All app creation moves inside `build_fastapi_app(config)`. The startup event (embedding preload + background cleanup) stays — only the config loading call is removed since config is now passed as a parameter.

- [ ] **Step 1: Read the current file**

Read `src/api/main.py` (105 lines) before editing.

- [ ] **Step 2: Rewrite `src/api/main.py`**

```python
# src/api/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from src.api.routes import chat, health, configuration, metrics, sessions
from src.api.utils.error_handlers import validation_exception_handler, general_exception_handler


def build_fastapi_app(config) -> FastAPI:
    """
    FastAPI app factory.

    Args:
        config: AppConfig from get_config().  Passed in so this function
                has no I/O side-effects (no config loading here).

    Returns:
        Fully configured FastAPI application, ready for uvicorn.
    """
    app = FastAPI(
        title="Chatbot API",
        description="FastAPI-based chatbot service with LangGraph integration",
        version="1.0.0",
    )

    @app.on_event("startup")
    async def startup_event():
        """
        Pre-warm heavy resources at startup.

        Config is already loaded by the launcher — only I/O-heavy tasks live here.
        """
        # Preload embedding model to avoid HuggingFace timeouts on first request
        try:
            from src.graphs.generic_text2sql.business_rules_vector_store import preload_embedding_model
            print("[STARTUP] Preloading embedding model (first run may take 1-2 minutes)...")
            model_loaded = preload_embedding_model()
            if model_loaded:
                print("[STARTUP] [OK] Embedding model cached successfully")
            else:
                print("[STARTUP] [WARN] Embedding model preload failed (will retry on first use)")
        except Exception as e:
            print(f"[STARTUP] [WARN] Failed to preload embedding model: {e}")

        # Start background table cleanup
        try:
            import os
            from src.graphs.generic_text2sql.table_registry import get_table_registry
            db_connection_string = os.getenv("DATABASE_URL")
            if db_connection_string:
                registry = get_table_registry()
                registry.start_background_cleanup(
                    db_connection_string=db_connection_string,
                    interval=300,
                )
                print("[STARTUP] Started background table cleanup (interval=300s)")
            else:
                print("[STARTUP] Warning: DATABASE_URL not set, skipping background table cleanup")
        except Exception as e:
            print(f"[STARTUP] Warning: Failed to start background table cleanup: {e}")

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)

    # Routers
    app.include_router(health.router, prefix="/api/health", tags=["Health"])
    app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
    app.include_router(configuration.router, prefix="/api/configuration", tags=["Configuration"])
    app.include_router(metrics.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")

    @app.get("/")
    async def root():
        return {"message": "Chatbot API", "version": "1.0.0", "docs": "/docs"}

    return app
```

- [ ] **Step 3: Verify the module imports without error**

```
python -c "from src.api.main import build_fastapi_app; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/api/main.py
git commit -m "refactor: convert src/api/main.py to build_fastapi_app(config) factory"
```

---

### Task 4: `ApiLauncher` — `src/launch/api_launcher.py`

**Files:**
- Create: `src/launch/api_launcher.py`
- Create: `tests/test_launcher_factory.py` (started here, extended in Task 7)

- [ ] **Step 1: Write failing tests for ApiLauncher**

```python
# tests/test_launcher_factory.py
import pytest
from unittest.mock import patch, MagicMock


# ── ApiLauncher ────────────────────────────────────────────────────────────────

def test_api_launcher_get_asgi_app_returns_fastapi(mock_config):
    """get_asgi_app() delegates to build_fastapi_app and returns the result."""
    fake_app = MagicMock()
    with patch("src.launch.api_launcher.get_config", return_value=mock_config), \
         patch("src.launch.api_launcher.build_fastapi_app", return_value=fake_app) as mock_build:
        from src.launch.api_launcher import ApiLauncher
        launcher = ApiLauncher()
        result = launcher.get_asgi_app()
        mock_build.assert_called_once_with(mock_config)
        assert result is fake_app


def test_api_launcher_run_raises_when_api_key_missing():
    """run() raises RuntimeError if api_key is absent."""
    mock_cfg = MagicMock()
    mock_cfg.llm.api_key = ""        # empty = missing
    with patch("src.launch.api_launcher.get_config", return_value=mock_cfg):
        from src.launch.api_launcher import ApiLauncher
        launcher = ApiLauncher()
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            launcher.run()


@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.llm.api_key = "sk-test"
    return cfg
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_launcher_factory.py -v
```

Expected: `ImportError` — `src.launch.api_launcher` does not exist yet.

- [ ] **Step 3: Create `src/launch/api_launcher.py`**

```python
# src/launch/api_launcher.py
import uvicorn
from src.core.app_config import get_config
from src.api.main import build_fastapi_app

DEFAULT_PORT = 8089


class ApiLauncher:
    """Launches the FastAPI + uvicorn server."""

    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = get_config(config_path)

    def get_asgi_app(self):
        """Return the ASGI app — used by PyInstaller / api_app.py."""
        return build_fastapi_app(self.config)

    def run(self, port: int = DEFAULT_PORT):
        """Start uvicorn. Raises RuntimeError if OPENAI_API_KEY is missing."""
        if not self.config.llm.api_key:
            raise RuntimeError(
                "OPENAI_API_KEY eksik — config/.env kontrol et"
            )
        uvicorn.run(self.get_asgi_app(), host="0.0.0.0", port=port)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_launcher_factory.py::test_api_launcher_get_asgi_app_returns_fastapi \
       tests/test_launcher_factory.py::test_api_launcher_run_raises_when_api_key_missing -v
```

Expected: 2 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/launch/api_launcher.py tests/test_launcher_factory.py
git commit -m "feat: add ApiLauncher to src/launch"
```

---

### Task 5: `GradioLauncher` — `src/launch/gradio_launcher.py`

**Files:**
- Create: `src/launch/gradio_launcher.py`

- [ ] **Step 1: Create `src/launch/gradio_launcher.py`**

```python
# src/launch/gradio_launcher.py
from src.core.app_config import get_config
from src.launch._chat_service import build_chat_service
from src.interfaces.gradio_interface import GradioInterface


class GradioLauncher:
    """Launches the Gradio demo interface."""

    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = get_config(config_path)

    def run(self):
        chat_service = build_chat_service(self.config)
        GradioInterface(chat_service).run(server_port=7860)
```

- [ ] **Step 2: Verify import**

```
python -c "from src.launch.gradio_launcher import GradioLauncher; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/launch/gradio_launcher.py
git commit -m "feat: add GradioLauncher to src/launch"
```

---

### Task 6: `CliLauncher` + Fix `src/interfaces/cli_interface.py`

**Files:**
- Create: `src/launch/cli_launcher.py`
- Modify: `src/interfaces/cli_interface.py`

The CLI interface currently imports from `src.api.chat_service` (the old, soon-to-be-deleted service) and passes request objects to methods that now take plain `str` in the canonical `src/api/services/chat_service.py`.

Canonical signature differences to fix:
- `get_history_async(session_id: str)` — was `get_history_async(HistoryRequest)`; response `.messages` still works
- `clear_history_async(session_id: str) -> int` — was `clear_history_async(ClearHistoryRequest)` returning object with `.cleared_count`; response is now `int`
- `end_session_async` — does not exist in canonical; remove cleanup call

- [ ] **Step 1: Read `src/interfaces/cli_interface.py` (295 lines)**

Read the file before editing.

- [ ] **Step 2: Fix the import + update method calls in `cli_interface.py`**

Replace lines 1–24 (imports):

```python
"""
CLI Interface - Refactored Architecture

Simple command-line interface for the refactored chatbot.

Features:
- Uses ChatService (orchestration layer)
- Sync operation (blocking input/output)
- Easy to test
- Minimal dependencies
"""

import asyncio
from typing import Optional

from src.api.services.chat_service import ChatService
from src.api.models.requests.chat import (
    SessionStartRequest,
    ChatMessageRequest,
)
```

Replace the `_show_history` method (lines 95–123):

```python
    async def _show_history(self):
        """Show conversation history."""
        if not self.session_id:
            print("[FAIL] No active session\n")
            return

        try:
            response = await self.chat_service.get_history_async(self.session_id)

            if not response.messages:
                print("(No messages yet)\n")
                return

            print("\n" + "="*60)
            print("Conversation History")
            print("="*60)

            for msg in response.messages:
                role = msg.role.upper()
                content = msg.content
                print(f"\n[{role}]")
                print(f"{content}")

            print("\n" + "="*60 + "\n")

        except Exception as e:
            print(f"[FAIL] Error retrieving history: {str(e)}\n")
```

Replace the `_clear_history` method (lines 125–137):

```python
    async def _clear_history(self):
        """Clear conversation."""
        if not self.session_id:
            print("[FAIL] No active session\n")
            return

        try:
            cleared_count = await self.chat_service.clear_history_async(self.session_id)
            print(f"[OK] Cleared {cleared_count} messages\n")
        except Exception as e:
            print(f"[FAIL] Error clearing history: {str(e)}\n")
```

Replace the cleanup block in `run()` (lines 271–279):

```python
        # Cleanup — no end_session in canonical ChatService
        pass
```

That is, remove the `try/except` block that calls `end_session_async`. The full `run()` method tail becomes:

```python
        # Cleanup
        pass
```

- [ ] **Step 3: Create `src/launch/cli_launcher.py`**

```python
# src/launch/cli_launcher.py
import asyncio
from src.core.app_config import get_config
from src.launch._chat_service import build_chat_service
from src.interfaces.cli_interface import CLIInterface


class CliLauncher:
    """Launches the interactive CLI interface (development)."""

    def __init__(self, config_path: str = "config/config.yaml"):
        self.config = get_config(config_path)

    def run(self):
        chat_service = build_chat_service(self.config)
        asyncio.run(CLIInterface(chat_service).run())
```

- [ ] **Step 4: Verify imports**

```
python -c "from src.launch.cli_launcher import CliLauncher; print('OK')"
python -c "from src.interfaces.cli_interface import CLIInterface; print('OK')"
```

Expected: both print `OK`.

- [ ] **Step 5: Commit**

```bash
git add src/launch/cli_launcher.py src/interfaces/cli_interface.py
git commit -m "feat: add CliLauncher; fix cli_interface broken import and method signatures"
```

---

### Task 7: `src/launch/__init__.py` — `get_launcher()` Factory

**Files:**
- Modify: `src/launch/__init__.py`
- Modify: `tests/test_launcher_factory.py` (add factory tests)

- [ ] **Step 1: Add factory tests to `tests/test_launcher_factory.py`**

Append to the existing file:

```python
# ── get_launcher ───────────────────────────────────────────────────────────────

def test_get_launcher_returns_api_launcher():
    from src.launch import get_launcher
    from src.launch.api_launcher import ApiLauncher
    with patch("src.launch.api_launcher.get_config", return_value=MagicMock()):
        launcher = get_launcher("api")
        assert isinstance(launcher, ApiLauncher)


def test_get_launcher_returns_gradio_launcher():
    from src.launch import get_launcher
    from src.launch.gradio_launcher import GradioLauncher
    with patch("src.launch.gradio_launcher.get_config", return_value=MagicMock()):
        launcher = get_launcher("gradio")
        assert isinstance(launcher, GradioLauncher)


def test_get_launcher_returns_cli_launcher():
    from src.launch import get_launcher
    from src.launch.cli_launcher import CliLauncher
    with patch("src.launch.cli_launcher.get_config", return_value=MagicMock()):
        launcher = get_launcher("cli")
        assert isinstance(launcher, CliLauncher)


def test_get_launcher_raises_on_unknown_interface():
    from src.launch import get_launcher
    with pytest.raises(ValueError, match="Bilinmeyen interface"):
        get_launcher("flask")
```

- [ ] **Step 2: Run new tests to confirm they fail**

```
pytest tests/test_launcher_factory.py -k "get_launcher" -v
```

Expected: `ImportError` — `get_launcher` not yet defined in `src/launch/__init__.py`.

- [ ] **Step 3: Update `src/launch/__init__.py`**

```python
# src/launch/__init__.py
from src.launch.api_launcher import ApiLauncher
from src.launch.gradio_launcher import GradioLauncher
from src.launch.cli_launcher import CliLauncher

_LAUNCHERS = {
    "api": ApiLauncher,
    "gradio": GradioLauncher,
    "cli": CliLauncher,
}


def get_launcher(interface: str, config_path: str = "config/config.yaml"):
    """
    Return the launcher for the requested interface.

    Args:
        interface: One of "api", "gradio", "cli".
        config_path: Path to config YAML, forwarded to the launcher.

    Raises:
        ValueError: If interface is not recognised.
    """
    if interface not in _LAUNCHERS:
        raise ValueError(
            f"Bilinmeyen interface: {interface!r}. Seçenekler: {list(_LAUNCHERS)}"
        )
    return _LAUNCHERS[interface](config_path)
```

- [ ] **Step 4: Run all launcher tests**

```
pytest tests/test_launcher_factory.py -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/launch/__init__.py tests/test_launcher_factory.py
git commit -m "feat: add get_launcher() factory to src/launch/__init__"
```

---

### Task 8: Simplify `main.py`

**Files:**
- Modify: `main.py`

The current `main.py` (142 lines) uses `build_chatbot()` with `RuntimeConfiguration`, `DependencyFactory`, `AdapterFactory`, `ChatbotBuilder`, and references broken imports (`flask_interface`, `fastapi_interface`). All of that is replaced by `get_launcher()`.

- [ ] **Step 1: Read current `main.py`** before editing.

- [ ] **Step 2: Rewrite `main.py`**

```python
"""
Forza Chatbot — CLI entry point.

Usage:
    python main.py --interface api      (default, production)
    python main.py --interface gradio   (demo)
    python main.py --interface cli      (development)
    python main.py --interface api --config path/to/config.yaml
"""
import argparse
from src.launch import get_launcher


def main():
    parser = argparse.ArgumentParser(description="Forza Chatbot")
    parser.add_argument(
        "--interface",
        choices=["api", "gradio", "cli"],
        default="api",
        help="Interface to launch (default: api)",
    )
    parser.add_argument(
        "--config",
        default="config/config.yaml",
        help="Path to config YAML (default: config/config.yaml)",
    )
    args = parser.parse_args()
    get_launcher(args.interface, args.config).run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify import chain**

```
python -c "import main; print('OK')"
```

Expected: `OK` (no import error).

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "refactor: simplify main.py to ~25 lines using get_launcher()"
```

---

### Task 9: Simplify `api_app.py`

**Files:**
- Modify: `api_app.py`

The current `api_app.py` (91 lines) loads .env, sets up PyInstaller paths, and logs extensively. The pysqlite3 monkey-patch and PyInstaller path manipulation are **kept** (required for the native exe to work). Config loading and startup logging are removed — handled by `ApiLauncher`.

- [ ] **Step 1: Read current `api_app.py`** before editing.

- [ ] **Step 2: Rewrite `api_app.py`**

```python
"""
api_app.py — PyInstaller entry point.

This file exists ONLY for PyInstaller native executable builds.
For normal execution use: python main.py --interface api
"""

# ── pysqlite3 monkey-patch (required for ChromaDB in the .exe) ────────────────
try:
    import pysqlite3 as sqlite3
    import sys
    sys.modules["sqlite3"] = sqlite3
except ImportError:
    pass  # Not running as compiled exe — regular sqlite3 is fine

# ── PyInstaller resource path setup ───────────────────────────────────────────
import sys
import os

if getattr(sys, "frozen", False):
    # Running as a compiled executable: make config/ discoverable relative to exe
    _base = os.path.dirname(sys.executable)
    if _base not in sys.path:
        sys.path.insert(0, _base)

# ── App ───────────────────────────────────────────────────────────────────────
from src.launch.api_launcher import ApiLauncher

launcher = ApiLauncher()
app = launcher.get_asgi_app()  # uvicorn reads this 'app' variable

if __name__ == "__main__":
    launcher.run()
```

- [ ] **Step 3: Verify import**

```
python -c "import api_app; print('OK')"
```

Expected: `OK` (no import error; uvicorn not actually started).

- [ ] **Step 4: Commit**

```bash
git add api_app.py
git commit -m "refactor: simplify api_app.py to ~20 lines using ApiLauncher"
```

---

### Task 10: Cleanup — Delete Old Files and Update Config

**Files:**
- Delete: `src/api/chat_service.py`
- Delete: `src/di_container.py`
- Modify: `src/__init__.py`
- Modify: `langgraph.json`

- [ ] **Step 1: Verify nothing still imports `src.api.chat_service`**

```
grep -r "from src.api.chat_service" src/ --include="*.py"
grep -r "from src.di_container" src/ --include="*.py"
grep -r "create_chatbot_dependencies" src/ --include="*.py"
```

Expected: zero matches (cli_interface was already fixed in Task 6, src/__init__.py export will be removed below).

- [ ] **Step 2: Delete old files**

```bash
git rm src/api/chat_service.py src/di_container.py
```

- [ ] **Step 3: Update `src/__init__.py`**

```python
# src/__init__.py
"""
Forza Chatbot — Refactored Architecture

Entry point for package-level imports.
Use src.launch.get_launcher() to start any interface.
"""
```

- [ ] **Step 4: Update `langgraph.json`**

Remove `generic_text2sql_graph` and `data_visualization_graph` (both functions were deleted in the cleanup branch):

```json
{
  "dependencies": ["."],
  "graphs": {
    "supervisor":   "src/graphs/graph_entrypoints.py:supervisor_graph",
    "routing":      "src/graphs/graph_entrypoints.py:routing_graph",
    "report_agent": "src/graphs/graph_entrypoints.py:report_agent_graph"
  },
  "env": "config/.env"
}
```

- [ ] **Step 5: Run the full test suite to catch regressions**

```
pytest tests/ -v --ignore=tests/test_enhanced_hitl.py --ignore=tests/test_llm_components.py
```

(Those two test files have pre-existing broken imports unrelated to this refactor.)

Expected: all tests PASSED (no new failures).

- [ ] **Step 6: Verify the three launch paths import correctly**

```bash
python -c "from src.launch import get_launcher; print(get_launcher.__module__)"
python -c "import main; print('main OK')"
python -c "import api_app; print('api_app OK')"
```

Expected: all three print without error.

- [ ] **Step 7: Commit**

```bash
git add src/__init__.py langgraph.json
git commit -m "chore: delete di_container + old chat_service; update langgraph.json to 3 graphs"
```

---

## Acceptance Criteria

- [ ] `python main.py --interface api` launches without error
- [ ] `python main.py --interface gradio` launches without error
- [ ] `python main.py --interface cli` launches without error
- [ ] `python main.py --config config/config.yaml --interface api` works
- [ ] `api_app.py` is importable (PyInstaller build prerequisite)
- [ ] `langgraph dev` with `langgraph.json` shows exactly 3 graphs
- [ ] Config is loaded only once per process (singleton confirmed by tests)
- [ ] All new tests pass
- [ ] `src/api/chat_service.py` and `src/di_container.py` are deleted
- [ ] `main.py` is ≤ 30 lines
- [ ] `api_app.py` is ≤ 25 lines
